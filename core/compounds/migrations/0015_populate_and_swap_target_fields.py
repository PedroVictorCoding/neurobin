# Migration to populate the new ForeignKey field and swap fields
from django.db import migrations, models
import django.db.models.deletion


def populate_target_fk(apps, schema_editor):
    """Populate the new ForeignKey field from the old CharField"""
    CompoundMechanismOfAction = apps.get_model('compounds', 'CompoundMechanismOfAction')
    Target = apps.get_model('compounds', 'Target')
    
    for mechanism in CompoundMechanismOfAction.objects.all():
        if mechanism.target_name and mechanism.target_name.strip():
            try:
                target = Target.objects.get(name=mechanism.target_name.strip())
                mechanism.target_name_fk = target
                mechanism.save()
            except Target.DoesNotExist:
                # Create target if it doesn't exist
                target = Target.objects.create(name=mechanism.target_name.strip())
                mechanism.target_name_fk = target
                mechanism.save()


def reverse_populate_target_fk(apps, schema_editor):
    """Reverse population (copy ForeignKey values back to CharField)"""
    CompoundMechanismOfAction = apps.get_model('compounds', 'CompoundMechanismOfAction')
    
    for mechanism in CompoundMechanismOfAction.objects.all():
        if mechanism.target_name_fk:
            mechanism.target_name = mechanism.target_name_fk.name
            mechanism.save()


class Migration(migrations.Migration):

    dependencies = [
        ('compounds', '0014_custom_target_migration'),
    ]

    operations = [
        # Populate the ForeignKey field from CharField values
        migrations.RunPython(populate_target_fk, reverse_populate_target_fk),
        
        # Remove the old CharField
        migrations.RemoveField(
            model_name='compoundmechanismofaction',
            name='target_name',
        ),
        
        # Rename the ForeignKey field to target_name
        migrations.RenameField(
            model_name='compoundmechanismofaction',
            old_name='target_name_fk',
            new_name='target_name',
        ),
    ]
