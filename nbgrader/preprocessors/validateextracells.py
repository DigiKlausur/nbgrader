import traceback

from ..nbgraderformat import ExtraCellValidator, ValidationError
from . import NbGraderPreprocessor

class ValidateExtraCells(NbGraderPreprocessor):
    """A preprocessor for checking that choice cells have valid solutions."""

    def preprocess(self, nb, resources):
        try:
            ExtraCellValidator().validate_nb(nb)
        except ValidationError:
            self.log.error(traceback.format_exc())
            msg = "Some choice cells seem to miss a solution. Please check them again."
            self.log.error(msg)
            raise ValidationError(msg)

        return nb, resources