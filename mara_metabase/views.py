
import flask
from mara_page import acl, navigation

blueprint = flask.Blueprint('mara_metabase', __name__, url_prefix='/')


acl_resource = acl.AclResource(name='Metabase')


@blueprint.before_app_first_request  # configuration needs to be loaded before we can access it
def _create_acl_resource_for_each_data_set():
    import mara_schema.config
    for data_set in mara_schema.config.data_sets():
        resource = acl.AclResource(name=data_set.name)
        acl_resource.add_child(resource)

def navigation_entry():
    return navigation.NavigationEntry(
        label='Metabase', uri_fn=lambda: flask.url_for('mara_metabase.metabase'),
        icon='bar-chart', description='Company wide dashboards, pivoting & ad hoc analysis')



@blueprint.route('/metabase')
@acl.require_permission(acl_resource)
def metabase():
    from . import config

    return flask.redirect(config.external_metabase_url())
