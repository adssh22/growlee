from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0002_wheelsegment'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='cta_label',
            field=models.CharField(default='Jouer maintenant', max_length=80),
        ),
        migrations.AddField(
            model_name='campaign',
            name='landing_headline',
            field=models.CharField(default='Tentez votre chance', max_length=160),
        ),
        migrations.AddField(
            model_name='campaign',
            name='landing_subheadline',
            field=models.CharField(default='Un jeu rapide pour découvrir votre surprise du jour.', max_length=255),
        ),
        migrations.AddField(
            model_name='campaign',
            name='review_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='campaign',
            name='game_type',
            field=models.CharField(choices=[('spin', 'Roue'), ('scratch', 'Ticket à gratter'), ('quiz', 'Quiz')], default='spin', max_length=20),
        ),
    ]
