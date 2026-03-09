from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='goal_skin',
            field=models.CharField(
                choices=[
                    ('general',     'General'),
                    ('anabolic',    'Anabolic'),
                    ('longevity',   'Longevity'),
                    ('cognition',   'Cognition'),
                    ('performance', 'Performance'),
                    ('recovery',    'Recovery'),
                    ('sleep',       'Sleep'),
                    ('fat-loss',    'Fat Loss'),
                ],
                default='general',
                help_text='Your primary goal defines the app color theme',
                max_length=20,
            ),
        ),
    ]
