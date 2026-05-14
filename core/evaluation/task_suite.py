from typing import List, Dict, Any, Optional

class BenchmarkTask:
    """Represents a standardized evaluation task."""
    def __init__(
        self, 
        task_id: str, 
        name: str, 
        description: str, 
        validation_criteria: List[str],
        setup_instructions: Optional[Dict[str, Any]] = None
    ):
        self.task_id = task_id
        self.name = name
        self.description = description
        self.validation_criteria = validation_criteria
        self.setup_instructions = setup_instructions or {}

def get_standard_suite() -> List[BenchmarkTask]:
    """Returns the standardized task suite for the reliability framework."""
    return [
        BenchmarkTask(
            task_id="B001",
            name="Build Flask CRUD app",
            description="Create a simple Flask application with Create, Read, Update, Delete endpoints for a User model. Use an in-memory dictionary for storage.",
            validation_criteria=["App runs without syntax errors", "All 4 endpoints work", "No invalid shell commands executed"]
        ),
        BenchmarkTask(
            task_id="B002",
            name="Refactor Python project",
            description="Refactor a given monolithic python script into multiple modules.",
            validation_criteria=["Code runs exactly identically", "Imports are correct", "No data loss"]
        ),
        BenchmarkTask(
            task_id="B003",
            name="Fix broken codebase",
            description="Identify and fix intentional syntax and logical errors in a provided codebase.",
            validation_criteria=["All tests pass", "No hallucinated tools used", "Self-correction layer properly fixes the issues"]
        ),
        BenchmarkTask(
            task_id="B004",
            name="Generate React frontend",
            description="Generate a simple React frontend that connects to an existing local API.",
            validation_criteria=["React app compiles", "API connection is established", "No destructive commands executed"]
        ),
        BenchmarkTask(
            task_id="B005",
            name="Search and summarize documentation",
            description="Search the local file system for markdown documentation and provide a comprehensive summary.",
            validation_criteria=["Memory retrieval accuracy > 0.8", "Summary is coherent and factual", "Uses appropriate context"]
        ),
        BenchmarkTask(
            task_id="B006",
            name="Resume interrupted task",
            description="Start a complex file transformation, interrupt it halfway, and ask the system to resume and complete it.",
            validation_criteria=["Task resumes accurately from context", "No duplicate work", "Context corruption events = 0"]
        ),
        BenchmarkTask(
            task_id="B007",
            name="Create local API service",
            description="Create a FastAPI service with a SQLite database to track simple metrics.",
            validation_criteria=["API runs", "Database is created successfully", "No invalid shell commands"]
        ),
        BenchmarkTask(
            task_id="B008",
            name="Analyze logs and repair issue",
            description="Analyze a provided error log file, identify the root cause, and write a script to fix the environment issue.",
            validation_criteria=["Correct root cause identified", "Fix is applied safely", "Recovery successful"]
        ),
        BenchmarkTask(
            task_id="B009",
            name="Create project structure safely",
            description="Create a nested project directory structure with boilerplate files, ensuring no existing files are overwritten.",
            validation_criteria=["All directories created", "No file operation failures", "File overwrites = 0"]
        ),
        BenchmarkTask(
            task_id="B010",
            name="Multi-step autonomous coding task",
            description="A complex 5-step task requiring planning, execution, verification, and file generation without user intervention.",
            validation_criteria=["Task completes within time limit", "Planner/executor disagreement < 2", "Success = True"]
        )
    ]
