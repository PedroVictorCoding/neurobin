from django.db import models
from django.conf import settings
from compounds.models import Compound


class IntakeLog(models.Model):
    TIME_OF_DAY_CHOICES = [
        ('morning', 'Morning'),
        ('afternoon', 'Afternoon'),
        ('night', 'Night'),
        ('pre-event', 'Pre-event'),
    ]
    UNIT_CHOICES = [
        ('mg', 'mg'),
        ('g', 'g'),
        ('mcg', 'mcg'),
        ('ml', 'ml'),
        ('drops', 'drops'),
        ('units', 'units'),
        ('other', 'Other'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    compound = models.ForeignKey(Compound, on_delete=models.CASCADE)
    stack_item = models.ForeignKey('stacks.StackItem', null=True, blank=True, on_delete=models.SET_NULL)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    amount = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=16, choices=UNIT_CHOICES, default='mg')
    time_of_day = models.CharField(max_length=10, choices=TIME_OF_DAY_CHOICES, default=None, blank=True, null=True)
    taken_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user} - {self.compound} @ {self.taken_at}"


class UserGoal(models.Model):
    GOAL_TYPE_CHOICES = [
        ("workout", "Workout"),
        ("health", "Health"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="weekly_goals",
    )
    name = models.CharField(max_length=120)
    goal_type = models.CharField(max_length=16, choices=GOAL_TYPE_CHOICES, default="health")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["goal_type", "name", "id"]

    def __str__(self):
        return f"{self.user.username} - {self.name}"


class UserGoalCompletion(models.Model):
    goal = models.ForeignKey(UserGoal, on_delete=models.CASCADE, related_name="completions")
    date = models.DateField()
    completed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "goal_id"]
        constraints = [
            models.UniqueConstraint(fields=["goal", "date"], name="unique_goal_day_completion"),
        ]

    def __str__(self):
        return f"{self.goal.name} on {self.date.isoformat()}: {'done' if self.completed else 'not done'}"


class RequestIPProfile(models.Model):
    ip_address = models.GenericIPAddressField(unique=True, db_index=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    total_requests = models.PositiveBigIntegerField(default=0)
    get_requests = models.PositiveBigIntegerField(default=0)
    post_requests = models.PositiveBigIntegerField(default=0)
    other_requests = models.PositiveBigIntegerField(default=0)
    error_requests = models.PositiveBigIntegerField(default=0)
    distinct_paths = models.PositiveIntegerField(default=0)
    last_path = models.CharField(max_length=512, blank=True)
    last_user_agent = models.TextField(blank=True)
    last_user = models.CharField(max_length=150, blank=True)

    abuse_checked_at = models.DateTimeField(null=True, blank=True)
    abuse_confidence_score = models.PositiveIntegerField(null=True, blank=True)
    abuse_total_reports = models.PositiveIntegerField(null=True, blank=True)
    abuse_num_distinct_users = models.PositiveIntegerField(null=True, blank=True)
    abuse_last_reported_at = models.DateTimeField(null=True, blank=True)
    abuse_usage_type = models.CharField(max_length=255, blank=True)
    abuse_isp = models.CharField(max_length=255, blank=True)
    abuse_domain = models.CharField(max_length=255, blank=True)
    abuse_country_code = models.CharField(max_length=8, blank=True)
    abuse_country_name = models.CharField(max_length=128, blank=True)
    abuse_hostnames = models.JSONField(default=list, blank=True)
    abuse_is_public = models.BooleanField(null=True, blank=True)
    abuse_is_whitelisted = models.BooleanField(null=True, blank=True)
    abuse_check_error = models.TextField(blank=True)

    is_throttle_active = models.BooleanField(default=False)
    throttle_limit_per_hour = models.PositiveSmallIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at", "ip_address"]

    def __str__(self):
        return self.ip_address


class RequestIPPathStat(models.Model):
    ip_profile = models.ForeignKey(
        RequestIPProfile,
        on_delete=models.CASCADE,
        related_name="path_stats",
    )
    path = models.CharField(max_length=512)
    method = models.CharField(max_length=10)
    request_count = models.PositiveBigIntegerField(default=0)
    last_seen_at = models.DateTimeField()

    class Meta:
        ordering = ["-request_count", "path"]
        constraints = [
            models.UniqueConstraint(
                fields=["ip_profile", "path", "method"],
                name="unique_ip_path_method_stat",
            )
        ]

    def __str__(self):
        return f"{self.ip_profile.ip_address} {self.method} {self.path} ({self.request_count})"
