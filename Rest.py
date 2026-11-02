# Rest.py — расширенный REST API для ER-редактора
# Запуск:
#   uvicorn Rest:app --reload --port 9000
# Проверка:
#   http://127.0.0.1:9000/docs

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="ER Editor API",
    description="REST API для редактора ER-диаграмм (проекты, диаграммы, валидация, экспорт).",
    version="0.2.0",
)


# ---------------------------------------------------------------
# Pydantic-модели
# ---------------------------------------------------------------
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Название проекта")
    description: str = Field(default="", description="Описание проекта")


class Project(ProjectCreate):
    id: int


class DiagramCreate(BaseModel):
    project_id: int = Field(..., description="ID проекта, к которому относится диаграмма")
    name: str = Field(..., min_length=1, description="Название диаграммы")
    diagram_type: str = Field(default="ER", description="Тип диаграммы")
    data: dict = Field(default_factory=dict, description="Данные диаграммы")


class Diagram(DiagramCreate):
    id: int


# ---------------------------------------------------------------
# In-memory хранилище (вместо БД)
# ---------------------------------------------------------------
projects: dict[int, Project] = {}
diagrams: dict[int, Diagram] = {}
next_project_id = 1
next_diagram_id = 1


# ---------------------------------------------------------------
# Служебные маршруты
# ---------------------------------------------------------------
@app.get("/", tags=["service"])
def home():
    return {
        "message": "ER Editor API запущен",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["service"])
def health():
    return {
        "status": "ok",
        "projects_count": len(projects),
        "diagrams_count": len(diagrams),
    }


# ---------------------------------------------------------------
# Проекты (5 маршрутов)
# ---------------------------------------------------------------
@app.get("/projects", response_model=list[Project], tags=["projects"])
def list_projects():
    """Список всех проектов."""
    return list(projects.values())


@app.post("/projects", response_model=Project, status_code=201, tags=["projects"])
def create_project(payload: ProjectCreate):
    """Создать проект."""
    global next_project_id
    project = Project(id=next_project_id, **payload.model_dump())
    projects[next_project_id] = project
    next_project_id += 1
    return project


@app.get("/projects/{project_id}", response_model=Project, tags=["projects"])
def get_project(project_id: int):
    """Получить проект по ID."""
    project = projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return project


@app.put("/projects/{project_id}", response_model=Project, tags=["projects"])
def update_project(project_id: int, payload: ProjectCreate):
    """Обновить проект."""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Проект не найден")
    project = Project(id=project_id, **payload.model_dump())
    projects[project_id] = project
    return project


@app.delete("/projects/{project_id}", tags=["projects"])
def delete_project(project_id: int):
    """Удалить проект (и все его диаграммы)."""
    if projects.pop(project_id, None) is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    # Каскадное удаление диаграмм
    to_delete = [did for did, d in diagrams.items() if d.project_id == project_id]
    for did in to_delete:
        del diagrams[did]
    return {"message": "Проект удалён", "id": project_id, "deleted_diagrams": len(to_delete)}


# ---------------------------------------------------------------
# Диаграммы (5 маршрутов)
# ---------------------------------------------------------------
@app.get("/diagrams", response_model=list[Diagram], tags=["diagrams"])
def list_diagrams():
    """Список всех диаграмм."""
    return list(diagrams.values())


@app.post("/diagrams", response_model=Diagram, status_code=201, tags=["diagrams"])
def create_diagram(payload: DiagramCreate):
    """Создать диаграмму."""
    global next_diagram_id
    if payload.project_id not in projects:
        raise HTTPException(status_code=422, detail="Проект с указанным project_id не существует")
    diagram = Diagram(id=next_diagram_id, **payload.model_dump())
    diagrams[next_diagram_id] = diagram
    next_diagram_id += 1
    return diagram


@app.get("/diagrams/{diagram_id}", response_model=Diagram, tags=["diagrams"])
def get_diagram(diagram_id: int):
    """Получить диаграмму по ID."""
    diagram = diagrams.get(diagram_id)
    if diagram is None:
        raise HTTPException(status_code=404, detail="Диаграмма не найдена")
    return diagram


@app.put("/diagrams/{diagram_id}", response_model=Diagram, tags=["diagrams"])
def update_diagram(diagram_id: int, payload: DiagramCreate):
    """Обновить диаграмму."""
    if diagram_id not in diagrams:
        raise HTTPException(status_code=404, detail="Диаграмма не найдена")
    if payload.project_id not in projects:
        raise HTTPException(status_code=422, detail="Проект с указанным project_id не существует")
    diagram = Diagram(id=diagram_id, **payload.model_dump())
    diagrams[diagram_id] = diagram
    return diagram


@app.delete("/diagrams/{diagram_id}", tags=["diagrams"])
def delete_diagram(diagram_id: int):
    """Удалить диаграмму."""
    if diagrams.pop(diagram_id, None) is None:
        raise HTTPException(status_code=404, detail="Диаграмма не найдена")
    return {"message": "Диаграмма удалена", "id": diagram_id}


# ---------------------------------------------------------------
# Валидация и экспорт
# ---------------------------------------------------------------
class ValidateRequest(BaseModel):
    diagram_id: int = Field(..., description="ID диаграммы для проверки")


@app.post("/validate", tags=["operations"])
def validate_diagram(req: ValidateRequest):
    """Проверить диаграмму на целостность.

    Правила:
    - диаграмма существует;
    - в data есть ключ 'entities' (список сущностей);
    - у каждой сущности есть 'name';
    - у каждой сущности есть 'attributes' (список).
    """
    diagram = diagrams.get(req.diagram_id)
    if diagram is None:
        raise HTTPException(status_code=404, detail="Диаграмма не найдена")

    errors: list[str] = []
    entities = diagram.data.get("entities")
    if not isinstance(entities, list):
        errors.append("Поле 'entities' отсутствует или не является списком")
    else:
        names = set()
        for i, ent in enumerate(entities):
            if not isinstance(ent, dict):
                errors.append(f"entities[{i}] не является объектом")
                continue
            name = ent.get("name")
            if not name:
                errors.append(f"entities[{i}] не имеет имени")
            elif name in names:
                errors.append(f"Дублирующееся имя сущности: {name}")
            else:
                names.add(name)
            if "attributes" not in ent:
                errors.append(f"entities[{i}] ({name or '?'}) не имеет attributes")
            elif not isinstance(ent["attributes"], list):
                errors.append(f"entities[{i}] ({name or '?'}) attributes должен быть списком")

    return {
        "diagram_id": req.diagram_id,
        "valid": len(errors) == 0,
        "errors": errors,
    }


class ExportRequest(BaseModel):
    diagram_id: int = Field(..., description="ID диаграммы для экспорта")
    format: str = Field(default="sql", description="Формат экспорта: sql")


@app.post("/export", tags=["operations"])
def export_diagram(req: ExportRequest):
    """Экспортировать диаграмму в SQL DDL.

    Генерирует CREATE TABLE по сущностям.
    """
    diagram = diagrams.get(req.diagram_id)
    if diagram is None:
        raise HTTPException(status_code=404, detail="Диаграмма не найдена")

    if req.format != "sql":
        raise HTTPException(status_code=422, detail=f"Формат '{req.format}' не поддерживается")

    entities = diagram.data.get("entities", [])
    if not isinstance(entities, list) or not entities:
        raise HTTPException(status_code=422, detail="В диаграмме нет сущностей для экспорта")

    sql_lines: list[str] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        name = ent.get("name", "unnamed")
        attrs = ent.get("attributes", []) or []
        cols = ["    id SERIAL PRIMARY KEY"]
        for attr in attrs:
            if isinstance(attr, dict):
                col_name = attr.get("name", "col")
                col_type = attr.get("type", "TEXT")
                cols.append(f"    {col_name} {col_type}")
            elif isinstance(attr, str):
                cols.append(f"    {attr} TEXT")
        sql_lines.append(f"CREATE TABLE {name} (\n" + ",\n".join(cols) + "\n);")

    sql = "\n\n".join(sql_lines)
    return {
        "diagram_id": req.diagram_id,
        "format": "sql",
        "content": sql,
    }
