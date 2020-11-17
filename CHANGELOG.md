# Changelog

## 1.2.0 (2020-11-16)

- Disable implicit automatic user sync: it needs now to be explicitly enabled to prevent
  accidental permissions overwrites of metabase instances where users and groups are not
  managed by mara (#5 & #6).

**Required Changes**

If you want users synced to metabase, you now need to enable that in your code:

```python
# e.g. in app/ui/__init__.py 
import mara_metabase.acl

mara_metabase.acl.enable_automatic_sync_of_users_and_permissions_to_metabase()
```

## 1.1.0 (2020-10-26)

- Add support for SQLServerDB as DWH database (#1 & #4)
- Include hidden/ sensitive fields in schema sync (#2)
- Fix typos in metabase.mk (#3)
- Make database setup more robust



## 1.0.0 - 1.0.1 (2020-07-13)

- Initial release
