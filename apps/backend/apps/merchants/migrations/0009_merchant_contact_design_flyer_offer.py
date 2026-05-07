from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merchants', '0008_merchant_billing_payment_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='contact_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='merchant',
            name='contact_phone',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='merchant',
            name='design_theme',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='merchant',
            name='inspiration_image',
            field=models.ImageField(blank=True, null=True, upload_to='merchants/inspiration/'),
        ),
        migrations.AddField(
            model_name='merchant',
            name='flyer_offer',
            field=models.CharField(blank=True, choices=[('1000_80', '1000 flyers · 80€'), ('5000_290', '5000 flyers · 290€'), ('custom', 'Volume personnalisé')], default='1000_80', max_length=40),
        ),
    ]
