"""Typed Provider SDK v0 family seams."""

from typing import Literal, Protocol

from .contracts import Provider, ProviderFamily


class PartProvider(Provider, Protocol):
    family: Literal[ProviderFamily.PART]


class SolverProvider(Provider, Protocol):
    family: Literal[ProviderFamily.SOLVER]


class RouterProvider(Provider, Protocol):
    family: Literal[ProviderFamily.ROUTER]


class LabInstrumentProvider(Provider, Protocol):
    family: Literal[ProviderFamily.LAB_INSTRUMENT]
