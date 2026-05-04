# Generated manually for Growlee gain claim links

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0005_walletpass_scan_code_walletpass_stamps_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='gamesession',
            name='claim_token',
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='gamesession',
            name='reward_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='gamesession',
            name='reward_available_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
