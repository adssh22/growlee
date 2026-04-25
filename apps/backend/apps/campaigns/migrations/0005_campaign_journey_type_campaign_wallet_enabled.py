from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0004_campaign_send_immediately_campaign_scheduled_for'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='journey_type',
            field=models.CharField(choices=[('premium_mobile', 'Mobile premium'), ('compact', 'Compact')], default='premium_mobile', max_length=40),
        ),
        migrations.AddField(
            model_name='campaign',
            name='wallet_enabled',
            field=models.BooleanField(default=True),
        ),
    ]
