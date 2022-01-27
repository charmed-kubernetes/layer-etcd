from charmhelpers.contrib.templating import jinja

from etcd_lib import render_grafana_dashboard


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
