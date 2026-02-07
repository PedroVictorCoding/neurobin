from django.db import models

class Compound(models.Model):
    name = models.CharField(max_length=200)
    smiles = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return self.name
