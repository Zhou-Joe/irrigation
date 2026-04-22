from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_add_patch_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='workreport',
            name='photos',
            field=models.JSONField(blank=True, default=list, help_text='照片文件路径列表', verbose_name='照片列表'),
        ),
    ]
