from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merchants', '0006_merchant_onboarding_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='flyer_style',
            field=models.CharField(blank=True, choices=[('basic', 'Basique'), ('premium', 'Premium'), ('bold', 'Impact')], default='', max_length=40),
        ),
        migrations.AddField(
            model_name='merchant',
            name='flyer_visual_approved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='merchant',
            name='flyer_order_status',
            field=models.CharField(blank=True, default='pending', max_length=40),
        ),
        migrations.AddField(
            model_name='merchant',
            name='onboarding_fee_paid',
            field=models.BooleanField(default=False),
        ),
    ]
