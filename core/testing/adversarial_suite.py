from pydantic import BaseModel

class AdversarialTask(BaseModel):
    task_id: str
    description: str
    hostile_conditions: list[str]

def get_adversarial_suite() -> list[AdversarialTask]:
    """
    Phase 7: Adversarial Benchmarks
    Unrealistically dirty, corrupted, and hostile tasks.
    """
    return [
        AdversarialTask(
            task_id="ADV-001",
            description="Refactor the user_auth.py module to use bcrypt.",
            hostile_conditions=["Filesystem locks randomly", "Subprocess crashes during pip install"]
        ),
        AdversarialTask(
            task_id="ADV-002",
            description="Build a multi-container Docker compose setup for a React/Node app.",
            hostile_conditions=["LLM outputs malformed JSON 40% of the time", "VRAM exhaustion warnings"]
        ),
        AdversarialTask(
            task_id="ADV-003",
            description="Resume the interrupted 'Data Migration' task from a corrupted checkpoint.",
            hostile_conditions=["Task graph checkpoint is missing dependencies", "Validator rejects correct operations"]
        )
    ]
