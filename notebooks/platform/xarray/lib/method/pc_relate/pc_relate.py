import numpy as np
import dask
import dask.array as da
from typing import Union


def gramian(a: dask.array) -> dask.array:
    """Returns gramian matrix of the given matrix"""
    return da.dot(a.T, a)


def __center(g: dask.array, mu: dask.array) -> dask.array:
    # TODO (rav): double check: 0.0 if not mu else g / 2 - mu
    return g / 2 - mu


def pc_relate(pcs: Union[dask.array.Array, np.ndarray],
              g: Union[dask.array.Array, np.ndarray],
              maf: float = 0.01) -> dask.array:
    """
    Compute PC-Relate https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4716688/

    :param pcs: PCs that best capture population structure within g,
                it has a length D
    :param g: variants x samples matrix, shape (v x s)
    :param maf: individual minor allele frequency filter. If an individual's estimated
                individual-specific minor allele frequency at a SNP is less than this value,
                that SNP will be excluded from the analysis for that individual.
                The default value is 0.01. Must be between (0.0, 1.0).
    :returns: (s x s) pairwise recent kinship estimation matrix
    """
    if maf <= 0.0 or maf >= 1.0:
        raise ValueError("MAF must be between (0.0, 1.0)")
    # 𝔼[gs|V] = 1β0 + Vβ, where 1 is a length _s_ vector of 1s, and β = (β1,...,βD)^T
    # is a length D vector of regression coefficients for each of the PCs
    pcsi = da.concatenate([da.from_array(np.ones((1, pcs.shape[1]))), pcs], axis=0).rechunk()
    q, r = da.linalg.qr(pcsi.T)
    # mu, eq: 3
    half_beta = da.matmul(da.matmul(da.linalg.inv(2 * r), q.T), g.T)
    mu = da.matmul(pcsi.T, half_beta).T
    # phi, eq: 4
    # TODO (rav): double check the MAF calculation
    variance = mu.map_blocks(lambda i: np.clip(i, 0.0 + maf, 1.0 - maf, i)).map_blocks(lambda i: i * (1.0 - i))
    stddev = da.sqrt(variance)
    centered_af = da.blockwise(__center, "ij", g, "ij", mu, "ij")
    return gramian(centered_af) / gramian(stddev)
