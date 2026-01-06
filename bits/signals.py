from django.db.models.signals import pre_delete, post_save, post_delete
from django.dispatch import receiver
from .models import Image, Item, Category
from django.core.cache import cache

@receiver(pre_delete, sender=Image)
def delete_image_file(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(save=False)

@receiver([post_save, post_delete], sender=Item)
@receiver([post_save, post_delete], sender=Image)
@receiver([post_save, post_delete], sender=Category)
def invalidate_cache(sender, **kwargs):
    try:
        cache.clear()
        print(f"Cache invalidated due to {sender.__name__} change")
    except Exception as e:
        print(f"Error invalidating cache for {sender.__name__}: {e}")