from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_modellodocumento'),
    ]

    operations = [
        migrations.AddField(
            model_name='modellodocumento',
            name='reparto',
            field=models.CharField(blank=True, db_column='Reparto', default='', max_length=100, verbose_name='Reparto'),
        ),
    ]
