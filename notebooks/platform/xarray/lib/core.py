from __future__ import annotations
import xarray as xr
import numpy as np
import inspect
import collections
import functools
from dataclasses import dataclass
from typing import Mapping, Sequence, Any, Type, Hashable
from xarray import Dataset
from . import DIM_VARIANT, DIM_SAMPLE, DIM_PLOIDY, DIM_ALLELE
from .utils import check_array, is_shape_match, to_snake_case
from .ops import get_mask_array, get_filled_array
from .config import config

# TODO:
# - Make type checks structural and not based on attrs

MISSING = -1


# Note: This is the convention pandas uses to demarcate groups of code
# (72 character HR w/ closing HR)
# ----------------------------------------------------------------------
# Utility Functions

def _mask(ds, fill_value=MISSING, var='data'):
    """Apply mask to dataset data variable"""
    is_masked = ds.get('is_masked')
    if is_masked is None:
        return ds[var]
    return xr.where(is_masked, fill_value, ds[var])


def _transmute(fn, ds, *args, **kwargs):
    """Create new dataset type with (overridable) default attribute propagation behavior"""
    # Preserve attributes
    kwargs['attrs'] = {**ds.attrs, **kwargs.get('attrs', {})}
    # Default any optional parameters to current values (these rarely change across dataset types)
    for p in inspect.signature(fn).parameters.values():
        # Only override data variables in result if not provided and present within the current dataset
        if p.default is None and p.name not in kwargs:
            kwargs[p.name] = ds.get(p.name)
    # Call factory method with positional (required) arguments as is, and any dynamic arguments as keyword args
    return fn(*args, **kwargs)


def _extract_array(data, is_masked):
    if is_masked is None:
        is_masked = get_mask_array(data)
        if is_masked is not None:
            data = get_filled_array(data, fill_value=MISSING)
    return data, is_masked


def _create_array(data, dims=None, set_coords=True, **kwargs):
    if isinstance(data, xr.DataArray):
        return data
    kwargs = dict(kwargs)
    if 'dims' not in kwargs and dims:
        kwargs['dims'] = dims
    if 'coords' not in kwargs and dims and set_coords:
        kwargs['coords'] = {dims[i]: np.arange(data.shape[i]) for i in range(data.ndim)}
    return xr.DataArray(data, **kwargs)


def _create_dataset(cls, arrays, **kwargs):
    # Validate arrays against constraints (types, dimensions, domains, etc.)
    arrays = {
        k: check_array(cls, v, types=cls.params[k].dtypes, dims=cls.params[k].dims)
        for k, v in arrays.items()
        if v is not None
    }

    # Infer masks provided within underlying arrays, if supported by backend
    if 'is_masked' in cls.params and 'data' in cls.params:
        arrays['data'], arrays['is_masked'] = _extract_array(arrays['data'], arrays.get('is_masked'))

    # Convert all arrays to xarray
    arrays = {
        k: _create_array(v, dims=cls.params[k].dims, **kwargs)
        for k, v in arrays.items()
        if v is not None
    }

    # Add dataset type to attributes
    kwargs = {'attrs': {**(kwargs.get('attrs', {})), **{'type': cls.__name__}}}
    return xr.Dataset(data_vars=arrays, **kwargs)

# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# Dataset Models


@dataclass
class ArrayParameter:
    dims: Sequence[str]
    dtypes: Sequence[Type]


def _params(dims, dtypes, core_vars=['data'], flag_vars=['is_masked', 'is_phased']) -> Mapping[Hashable, ArrayParameter]:
    return {
        **{v: ArrayParameter(dims, dtypes) for v in core_vars},
        **{v: ArrayParameter([DIM_VARIANT, DIM_SAMPLE], [np.bool_]) for v in flag_vars}
    }


class GeneticDataset:
    pass


def transmutation(target_dstype):
    def decorator(fn):
        if not hasattr(GeneticDataset, 'transmutations'):
            GeneticDataset.transmutations = collections.defaultdict(dict)
        GeneticDataset.transmutations[fn.__qualname__.split('.')[0]][target_dstype.__name__] = fn
        return fn
    return decorator


class GenotypeDosageDataset(GeneticDataset):

    params: Mapping[Hashable, ArrayParameter] = _params([DIM_VARIANT, DIM_SAMPLE], [np.floating])

    @classmethod
    def create(cls, data: Any, is_phased: Any = None, is_masked: Any = None, **kwargs) -> Dataset:
        arrays = dict(data=data, is_phased=is_phased, is_masked=is_masked)
        return _create_dataset(cls, arrays, **kwargs)


class GenotypeCountDataset(GeneticDataset):

    params: Mapping[Hashable, ArrayParameter] = _params(
        [DIM_VARIANT, DIM_SAMPLE], [np.integer], flag_vars=['is_masked'])

    @classmethod
    def create(cls, data: Any, is_masked: Any = None, **kwargs) -> Dataset:
        arrays = dict(data=data, is_masked=is_masked)
        return _create_dataset(cls, arrays, **kwargs)


class HaplotypeCallDataset(GeneticDataset):

    params: Mapping[Hashable, ArrayParameter] = _params(
        [DIM_VARIANT, DIM_SAMPLE], [np.integer])

    @classmethod
    def create(cls, data: Any, is_phased: Any = None, is_masked: Any = None, **kwargs) -> Dataset:
        arrays = dict(data=data, is_phased=is_phased, is_masked=is_masked)
        return _create_dataset(cls, arrays, **kwargs)


class GenotypeCallDataset(GeneticDataset):

    params: Mapping[Hashable, ArrayParameter] = _params(
        [DIM_VARIANT, DIM_SAMPLE, DIM_PLOIDY], [np.integer])

    @classmethod
    def create(cls, data: Any, is_phased: Any = None, is_masked: Any = None, **kwargs) -> Dataset:
        arrays = dict(data=data, is_phased=is_phased, is_masked=is_masked)
        return _create_dataset(cls, arrays, **kwargs)

    @staticmethod
    @transmutation(HaplotypeCallDataset)
    def to(ds: Dataset, contig: int) -> Dataset:
        """Convert to haplotypecalls"""
        # FIXME: nonsense for testing
        data = _mask(ds.assign(data=ds.data[..., contig]))
        return _transmute(HaplotypeCallDataset.create, ds, data)

    # pylint: disable=function-redefined
    @staticmethod
    @transmutation(GenotypeCountDataset)
    def to(ds: Dataset) -> Dataset:
        """Convert to genotype counts"""
        data = _mask(ds.assign(data=(ds.data > 0).sum(dim=DIM_PLOIDY)))
        return _transmute(GenotypeCountDataset.create, ds, data)


class GenotypeProbabilityDataset(GeneticDataset):

    params: Mapping[Hashable, ArrayParameter] = _params(
        [DIM_VARIANT, DIM_SAMPLE, DIM_PLOIDY, DIM_ALLELE], [np.floating])

    @classmethod
    def create(cls, data: Any, is_phased: Any = None, is_masked: Any = None, **kwargs) -> Dataset:
        arrays = dict(data=data, is_phased=is_phased, is_masked=is_masked)
        return _create_dataset(cls, arrays, **kwargs)

    @staticmethod
    @transmutation(GenotypeDosageDataset)
    def to(ds: Dataset) -> Dataset:
        if not is_shape_match(ds, {DIM_PLOIDY: 2, DIM_ALLELE: 2}):
            raise ValueError(
                'Dosage calculation currently only supported for bi-allelic, '
                'diploid arrays (ploidy and alelle dims must have size 2)')
        # Get array slices for ref and alt probabilities on each chromosome
        c0ref, c1ref = ds.data[..., 0, 0], ds.data[..., 1, 0]
        c0alt, c1alt = ds.data[..., 0, 1], ds.data[..., 1, 1]
        # Compute dosage as float in [0, 2]
        data = c0ref * c1alt + c0alt * c1ref + 2 * c0alt * c1alt
        data = _mask(ds.assign(data=data))
        return _transmute(GenotypeDosageDataset.create, ds, data)


class GenotypeAlleleCountDataset(GeneticDataset):

    params: Mapping[Hashable, ArrayParameter] = _params(
        [DIM_VARIANT, DIM_SAMPLE, DIM_PLOIDY], [np.integer],
        core_vars=['data', 'indexes'], flag_vars=['is_masked'])

    @classmethod
    def create(cls, data: Any, indexes: Any = None, is_masked: Any = None, **kwargs) -> Dataset:
        arrays = dict(data=data, indexes=indexes, is_masked=is_masked)
        return _create_dataset(cls, arrays, **kwargs)

    @classmethod
    def to(cls, ds, dstype):
        return dstype


def isdstype(ds: Dataset, cls: Type[GeneticDataset]):
    return ds.to.retyped().type == cls.__name__


_dstypes = {t.__name__: t for t in GeneticDataset.__subclasses__()}


def retype(ds: Dataset) -> Dataset:
    """Assign type for dataset based on attributes or structure

    The returned dataset is guaranteed to have a value for `type` in attrs, and it
    is either left alone if already present (possibly with assertion of structure)
    or set based on structure.
    """
    if 'type' in ds.attrs:
        if ds.type not in _dstypes:
            raise TypeError(f'Dataset has invalid type "{ds.type}" in attrs')
        # TODO: Assert that dataset is compliant with type, potentially with configuration
        # options allowing for this to be skipped
        return ds

    # TODO: Infer type based on structure
    raise ValueError('Dataset does not have required attribute "type"')


# ----------------------------------------------------------------------
# Accessor/Factory Functions


for dstype in GeneticDataset.__subclasses__():
    fn_name = to_snake_case(dstype.__name__)
    globals()[f'create_{to_snake_case(dstype.__name__)}'] = dstype.create


@xr.register_dataset_accessor("to")
class DatasetTransmutationAccessor():

    def __init__(self, ds):
        # Assert or assign type
        ds = retype(ds)

        # Monkey patch transmutation functions based on dataset type
        def add_fn(name, fn, ds):
            ifn = lambda *args, **kwargs: fn(ds, *args, **kwargs)
            ifn = functools.update_wrapper(ifn, fn)
            setattr(self, name, ifn)
        for dstype, fn in GeneticDataset.transmutations[ds.type].items():
            add_fn(to_snake_case(dstype), fn, ds)
        # Add transmutation to same type (returns self)
        add_fn(to_snake_case(ds.type), lambda _: ds, ds)
        self.ds = ds

    def retyped(self):
        """Get Dataset with guaranteed type assignment"""
        return self.ds


class Variables:

    @property
    def contig(self):
        return config.get('variable.contig', 'contig')

    @property
    def pos(self):
        return config.get('variable.pos', 'pos')

    @property
    def data(self):
        return 'data'

VARIABLES = Variables()