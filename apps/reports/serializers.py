from rest_framework import serializers

from apps.exams.models import ExamResult


class ReportRowSerializer(serializers.ModelSerializer):
    learnerId = serializers.UUIDField(source="learner_id", read_only=True)
    learnerName = serializers.SerializerMethodField()
    uln = serializers.SerializerMethodField()
    qualificationId = serializers.UUIDField(source="qualification_id", read_only=True)
    qualificationName = serializers.CharField(source="qualification.title", read_only=True)
    examId = serializers.UUIDField(source="exam_config_id", read_only=True)
    examTitle = serializers.CharField(source="exam_config.title", read_only=True)
    examDate = serializers.DateField(source="exam_date", format="%Y-%m-%d", read_only=True)
    invigilatorName = serializers.CharField(source="invigilator_name", read_only=True)
    scorePercent = serializers.IntegerField(source="score_percent", read_only=True)
    correctCount = serializers.IntegerField(source="correct_count", read_only=True)
    totalQuestions = serializers.IntegerField(source="total_questions", read_only=True)
    grade = serializers.CharField(read_only=True)
    passed = serializers.BooleanField(read_only=True)
    timeTakenSeconds = serializers.IntegerField(source="time_taken_seconds", read_only=True)
    violationCount = serializers.IntegerField(source="violation_count", read_only=True)
    reasonableAdjustments = serializers.CharField(source="reasonable_adjustments", read_only=True)
    attemptNumber = serializers.IntegerField(source="attempt_number", read_only=True)
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)

    class Meta:
        model = ExamResult
        fields = (
            "id",
            "learnerId",
            "learnerName",
            "uln",
            "qualificationId",
            "qualificationName",
            "examId",
            "examTitle",
            "examDate",
            "invigilatorName",
            "scorePercent",
            "correctCount",
            "totalQuestions",
            "grade",
            "passed",
            "timeTakenSeconds",
            "violationCount",
            "reasonableAdjustments",
            "attemptNumber",
            "submittedAt",
        )

    def get_learnerName(self, obj) -> str:
        return f"{obj.learner.first_name} {obj.learner.last_name}".strip()

    def get_uln(self, obj) -> str:
        profile = getattr(obj.learner, "learner_profile", None)
        return profile.uln if profile and profile.uln else ""


class ReportDetailSerializer(ReportRowSerializer):
    """
    GET /reports/{id}/ — powers the Exam Summary modal.
    Same fields as the list row + a pre-formatted time string so the
    frontend doesn't need to do its own seconds-to-mm:ss math.
    """
    timeTakenDisplay = serializers.SerializerMethodField()
    resultLabel = serializers.SerializerMethodField()

    class Meta(ReportRowSerializer.Meta):
        fields = ReportRowSerializer.Meta.fields + (
            "timeTakenDisplay",
            "resultLabel",
        )

    def get_timeTakenDisplay(self, obj) -> str:
        secs = obj.time_taken_seconds or 0
        m, s = divmod(secs, 60)
        return f"{m}m {s}s"

    def get_resultLabel(self, obj) -> str:
        return "PASSED" if obj.passed else "DID NOT PASS"
