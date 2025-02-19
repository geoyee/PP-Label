import os
import os.path as osp
import requests
import tarfile
import zipfile
from pathlib import Path

from tqdm import tqdm
import connexion

import pplabel
from pplabel.config import data_base_dir
from pplabel.api.schema import ProjectSchema
from pplabel.api.model import TaskCategory
from pplabel.config import basedir
from pplabel.task.util.file import copy, copycontent


def prep_samples(sample_dst: str = None):
    if sample_dst is None:
        sample_dst = osp.join(osp.expanduser("~"), ".pplabel", "sample")
    sample_source = osp.join(basedir, "sample")
    copycontent(sample_source, sample_dst)

    dsts = [
        "clas/multi/image/1.jpeg",
        "clas/multi/image/2.jpeg",
        "clas/multi/image/3.jpeg",
        "clas/multi/image/4.jpeg",
        "clas/single/1/1.jpeg",
        "clas/single/2/2.jpeg",
        "clas/single/3/3.jpeg",
        "clas/single/4/4.jpeg",
        "det/coco/JPEGImages/1.jpeg",
        "det/coco/JPEGImages/2.jpeg",
        "det/coco/JPEGImages/3.jpeg",
        "det/coco/JPEGImages/4.jpeg",
        "det/voc/JPEGImages/1.jpeg",
        "det/voc/JPEGImages/2.jpeg",
        "det/voc/JPEGImages/3.jpeg",
        "det/voc/JPEGImages/4.jpeg",
        "instance_seg/mask/JPEGImages/1.jpeg",
        "instance_seg/mask/JPEGImages/2.jpeg",
        "instance_seg/mask/JPEGImages/3.jpeg",
        "instance_seg/mask/JPEGImages/4.jpeg",
        "instance_seg/polygon/image/1.jpeg",
        "instance_seg/polygon/image/2.jpeg",
        "instance_seg/polygon/image/3.jpeg",
        "instance_seg/polygon/image/4.jpeg",
        "semantic_seg/mask/JPEGImages/1.jpeg",
        "semantic_seg/mask/JPEGImages/2.jpeg",
        "semantic_seg/mask/JPEGImages/3.jpeg",
        "semantic_seg/mask/JPEGImages/4.jpeg",
        "semantic_seg/polygon/image/1.jpeg",
        "semantic_seg/polygon/image/2.jpeg",
        "semantic_seg/polygon/image/3.jpeg",
        "semantic_seg/polygon/image/4.jpeg",
    ]
    img_path = osp.join(sample_source, "imgs")
    for dst in dsts:
        dst = osp.join(sample_dst, dst)
        src = osp.join(img_path, osp.basename(dst))
        copy(src, dst, make_dir=True)


def load_sample():
    prep_samples()

    task_category_id = connexion.request.json.get("task_category_id")

    sample_folder = {
        "classification": ["clas", "single"],
        "detection": ["det", "voc"],
        "semantic_segmentation": ["semantic_seg", "mask"],
        "instance_segmentation": ["instance_seg", "polygon"],
    }
    task_category = TaskCategory._get(task_category_id=task_category_id)
    data_dir = osp.join(
        osp.expanduser("~"), ".pplabel", "sample", *sample_folder[task_category.name]
    )
    print(task_category.name, task_category)

    project = {
        "name": f"Sample Project - {task_category.name}",
        "description": f"A {task_category.name} sample project created by PP-Label",
        "task_category_id": str(task_category_id),
        "data_dir": data_dir,
    }
    project = ProjectSchema().load(project)

    if task_category is None:
        handler = pplabel.task.BaseTask(project)
    else:
        handler = eval(task_category.handler)(project, data_dir=data_dir)

    handler.default_importer()

    print(handler.project)

    return {"project_id": handler.project.project_id}, 200
