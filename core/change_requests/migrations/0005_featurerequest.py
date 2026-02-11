import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('change_requests', '0004_remove_compound_version_table'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FeatureRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('request_type', models.CharField(choices=[('feature', 'Feature Request'), ('consideration', 'Consideration')], default='feature', max_length=20)),
                ('title', models.CharField(max_length=200)),
                ('details', models.TextField()),
                ('display_name', models.CharField(blank=True, max_length=100)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('source_page', models.CharField(blank=True, max_length=255)),
                ('user_agent', models.CharField(blank=True, max_length=255)),
                ('status', models.CharField(choices=[('new', 'New'), ('reviewed', 'Reviewed'), ('planned', 'Planned'), ('done', 'Done'), ('rejected', 'Rejected')], default='new', max_length=20)),
                ('admin_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('submitted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='feature_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Feature Request',
                'verbose_name_plural': 'Feature Requests',
                'ordering': ['-created_at'],
            },
        ),
    ]
