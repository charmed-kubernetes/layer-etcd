import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--series",
        type=str,
        default="jammy",
        help="Set series for the machine units",
    )


@pytest.fixture()
def series(request):
    return request.config.getoption("--series")
