from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import Role, StaffProfile, User, LearnerProfile

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.role == Role.LEARNER:
        LearnerProfile.objects.create(user=instance)

    elif instance.role in [Role.ADMIN, Role.INVIGILATOR]:
        StaffProfile.objects.create(user=instance)