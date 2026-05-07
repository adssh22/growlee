from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merchants', '0007_merchant_flyer_billing'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='billing_payment_type',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='merchant',
            name='billing_payment_reference',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
