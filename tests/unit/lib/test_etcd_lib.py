from typing import Any

from charmhelpers.contrib.templating import jinja
import pytest

from etcd_lib import render_grafana_dashboard, build_uri


def test_render_grafana_dashboard():
    """Test loading of Grafana dashboard."""
    datasource = "prometheus"
    raw_template = (
        '{{"panels": [{{"datasource": "{} - '
        'Juju generated source"}}]}}'.format(datasource)
    )
    expected_dashboard = {
        "panels": [{"datasource": "{} - Juju generated source".format(datasource)}]
    }

    jinja.render.return_value = raw_template
    rendered_dashboard = render_grafana_dashboard(datasource)

    assert rendered_dashboard == expected_dashboard


@pytest.mark.parametrize(
    "src,result",
    [
        ("1.2.3.4", "https://1.2.3.4:8080"),
        ("2001:0db8::0001", "https://[2001:db8::1]:8080"),
        ("my.host.io", "https://my.host.io:8080"),
    ],
)
def test_build_uri(src: Any, result: str):
    assert build_uri("https", src, 8080) == result
