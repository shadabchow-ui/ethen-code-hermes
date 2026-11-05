"""Explicit offline package inputs survive the credential-scrubbing native runner."""
def pytest_addoption(parser):
    parser.addoption('--ethen-artifact')
    parser.addoption('--ethen-cache')
    parser.addoption('--ethen-tools')
    parser.addoption('--ethen-evidence')
