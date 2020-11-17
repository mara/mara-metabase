"""Automatic syncing of users, groups and permissions from Mara to Metabase"""


def sync():
    import mara_acl.keys
    import mara_db.postgresql
    from mara_acl import permissions
    from . import config
    from . import views

    from .client import MetabaseClient

    client = MetabaseClient()

    metabase_groups = {group['name']: group['id'] for group in client.get('/api/permissions/group')}
    metabase_users = {user['email']: user['id'] for user in client.get('/api/user?include_deactivated=true')}
    deactivated_metabase_users = {user['email']: user['id'] for user
                                  in client.get('/api/user?include_deactivated=true') if not user['is_active']}
    mara_roles = set()
    mara_users = set()

    # add roles and users from mara that don't exist in metabase
    with mara_db.postgresql.postgres_cursor_context('mara') as cursor:
        cursor.execute('SELECT role, array_agg(email) FROM acl_user GROUP BY role')
        for role, emails in cursor.fetchall():
            mara_roles.add(role)
            if role not in metabase_groups:
                result = client.post('/api/permissions/group', {'name': role})
                metabase_groups[result['name']] = result['id']
            for email in emails:
                if email != 'guest@localhost':
                    mara_users.add(email)
                    first_name, last_name = email.replace('@', '.').split('.')[0:2]
                    metabase_user = {'email': email,
                                     'first_name': first_name.capitalize(),
                                     'last_name': last_name.capitalize(),
                                     'is_super_user': True if role == 'Administrators' else False,
                                     'google_auth': True,
                                     'group_ids': [metabase_groups[role], metabase_groups['All Users']]}
                    if email not in metabase_users:
                        print(client.post('/api/user', metabase_user))
                    else:
                        if email in deactivated_metabase_users:
                            print(client.put(f'/api/user/{metabase_users[email]}/reactivate', metabase_user))
                        print(client.put(f'/api/user/{metabase_users[email]}', metabase_user))

    # delete groups that don't exist as roles in Mara
    for group_name, id in metabase_groups.items():
        if group_name not in mara_roles and group_name not in ['All Users', 'Administrators']:
            client.delete(f'/api/permissions/group/{id}')

    for email, id in metabase_users.items():
        if email not in mara_users and email != config.metabase_admin_email():
            client.delete(f'/api/user/{id}')

    # get current permissions
    graph = client.get('/api/permissions/graph')

    # create data set acl resources (the were not created when run through cli)
    if not views.acl_resource.children:
        views._create_acl_resource_for_each_data_set()

    # all mara acl permissions
    all_permissions = permissions.all_permissions()

    # all tables known in Metabase
    tables = {table['name']: table for table in client.get('/api/table')}

    database_id = client.get('/api/database/')[0]['id']

    # build and upload new permission graph
    new_graph = {'groups': {}, 'revision': graph['revision']}
    for metabase_group, group_id in metabase_groups.items():
        table_permissions = {}
        if metabase_group == 'Administrators':
            new_graph['groups'][group_id] = {database_id: {'native': 'write', 'schemas': 'all'}}
        elif metabase_group == 'All Users':
            new_graph['groups'][group_id] = {database_id: {'native': 'none', 'schemas': 'none'}}
        else:
            for resource in views.acl_resource.children:
                allowed = any([permission[0] == mara_acl.keys.user_key(metabase_group)
                               and (mara_acl.keys.resource_key(resource).startswith(permission[1]))
                               for permission in all_permissions.values()])
                table = tables.get(resource.name)
                if table:
                    schema = table['schema']
                    if schema not in table_permissions:
                        table_permissions[schema] = {}
                    table_permissions[schema][table['id']] = 'all' if allowed else 'none'

            if table_permissions:
                new_graph['groups'][group_id] = {database_id: {'schemas': table_permissions}}

    print(client.put('/api/permissions/graph', new_graph))


def enable_automatic_sync_of_users_and_permissions_to_metabase():
    import mara_acl.permissions
    import mara_acl.users
    from mara_app.monkey_patch import wrap
    import flask

    def sync_and_catch_errors():
        try:
            sync()
        except Exception as e:
            import traceback
            flask.flash(f'Error while syncing to Metabase: {e}', category='danger')
            print(traceback.format_exc())

    @wrap(mara_acl.permissions.save_permissions)
    def save_permission(original_fn, permissions):
        original_fn(permissions)
        sync_and_catch_errors()

    @wrap(mara_acl.users.add_user)
    def add_user(original_fn, email: str, role: str):
        original_fn(email, role)
        sync_and_catch_errors()

    @wrap(mara_acl.users.delete_user)
    def delete_user(original_fn, email):
        original_fn(email)
        sync_and_catch_errors()

    @wrap(mara_acl.users.change_role)
    def change_role(original_fn, email, new_role):
        original_fn(email, new_role)
        sync_and_catch_errors()
