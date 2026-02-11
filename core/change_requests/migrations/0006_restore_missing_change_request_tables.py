from django.db import migrations


def restore_missing_change_request_tables(apps, schema_editor):
    """
    Repair migration for environments where old migrations were applied from an
    earlier graph that dropped ChangeRequest tables.

    This migration is idempotent: it only creates missing tables and leaves
    existing tables/data untouched.
    """
    existing_tables = set(schema_editor.connection.introspection.table_names())

    ChangeRequest = apps.get_model("change_requests", "ChangeRequest")
    ChangeRequestComment = apps.get_model("change_requests", "ChangeRequestComment")
    AppliedChange = apps.get_model("change_requests", "AppliedChange")

    for model in (ChangeRequest, ChangeRequestComment, AppliedChange):
        table_name = model._meta.db_table
        if table_name in existing_tables:
            continue
        schema_editor.create_model(model)
        existing_tables.add(table_name)


class Migration(migrations.Migration):
    dependencies = [
        ("change_requests", "0005_featurerequest"),
    ]

    operations = [
        migrations.RunPython(restore_missing_change_request_tables, migrations.RunPython.noop),
    ]

