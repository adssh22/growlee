from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merchants', '0002_merchant_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='body_font',
            field=models.CharField(choices=[('inter', 'Inter'), ('poppins', 'Poppins'), ('manrope', 'Manrope'), ('dm-sans', 'DM Sans')], default='inter', max_length=40),
        ),
        migrations.AddField(
            model_name='merchant',
            name='heading_font',
            field=models.CharField(choices=[('inter', 'Inter'), ('poppins', 'Poppins'), ('manrope', 'Manrope'), ('dm-sans', 'DM Sans')], default='inter', max_length=40),
        ),
        migrations.AddField(
            model_name='merchant',
            name='surface_color',
            field=models.CharField(default='#ffffff', max_length=20),
        ),
        migrations.AddField(
            model_name='merchant',
            name='text_color',
            field=models.CharField(default='#1f2937', max_length=20),
        ),
    ]
