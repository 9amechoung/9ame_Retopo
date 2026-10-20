"""Relax retopo vertices while keeping them on the live surface."""

from nine_retopo import geometry, mesh_utils
from nine_retopo.surface import Projector


def relax_vertices(mesh, vertex_ids, iterations=5, strength=0.5,
                   keep_boundary=True, projector=None):
    """Relax ``vertex_ids`` on ``mesh`` and return their new positions."""
    neighbors, boundary = mesh_utils.topology(mesh)
    positions = dict(enumerate(mesh_utils.get_points(mesh)))
    movable = [v for v in vertex_ids if not (keep_boundary and v in boundary)]
    weights = dict.fromkeys(movable, strength)

    for _ in range(iterations):
        moved = geometry.relax_step(positions, neighbors, weights)
        if projector:
            moved = projector.project_dict(moved)
        positions.update(moved)

    result = {v: positions[v] for v in movable}
    mesh_utils.set_points(mesh, result)
    return result


@mesh_utils.undoable
def relax_selection(iterations=5, strength=0.5, keep_boundary=True, snap=True):
    """Relax the selected vertices (or whole meshes)."""
    projector = Projector() if snap else None
    selection = mesh_utils.selected_vertices()
    if not selection:
        raise RuntimeError("Select retopo vertices, faces, edges or meshes to relax.")
    count = 0
    for mesh, ids in selection.items():
        if projector and mesh == projector.name:
            continue
        count += len(relax_vertices(mesh, ids, iterations, strength,
                                    keep_boundary, projector))
    return count
