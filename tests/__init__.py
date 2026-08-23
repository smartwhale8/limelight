"""Test suite for limelight.

The whole suite runs without hardware and without network access. Device access goes
through :class:`tests.fakes.FakeTransport`, which reproduces the real firmware's
behaviour, including its two brightness defects.
"""
