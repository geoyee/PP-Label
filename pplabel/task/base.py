import os
import os.path as osp
import json

from pplabel.api import Annotation, Data, Label, Project, Task
from pplabel.api.model import project
from pplabel.api.util import rand_color
from pplabel.config import db
from pplabel.task.util import image_extensions, listdir

"""
Base for import/export and other task specific operations.
"""


class BaseTask:
    def __init__(self, project):
        """
        Args:
            project (int|dict): If the project exists, self.project will be queried from db with parameter project as project_id or with project.project_id. Else the project will be created.
        """

        # 1. set project
        if isinstance(project, int):
            curr_project = Project._get(project_id=project)
            if curr_project is None:
                raise RuntimeError(f"No project with project_id {project}")
        else:
            curr_project = Project._get(project_id=project.project_id)
            if curr_project is None:
                db.session.add(project)
                db.session.commit()
                curr_project = project
        self.project = curr_project

        os.makedirs(self.project.data_dir, exist_ok=True)

        # 2. set current label max id
        # next added label will have id label_max_id+1, so label.id starts from 1
        self.label_max_id = 0
        for label in project.labels:
            self.label_max_id = max(self.label_max_id, label.id)

        # 3. read dataset split
        self.split = self.read_split()

        # 4. create labels specified in labels.txt
        label_names_path = None
        if project.other_settings is not None:
            if isinstance(project.other_settings, str):
                other_settings = json.loads(project.other_settings)
            else:
                other_settings = project.other_settings
            label_names_path = other_settings.get("label_names_path", None)

        if label_names_path is None:
            label_names_path = osp.join(project.data_dir, "labels.txt")
        if osp.exists(label_names_path):
            self.import_label_names(label_names_path)

        # 5. polupate label colors
        self.populate_label_colors()

        # 6. get curr datapaths
        tasks = Task._get(project_id=project.project_id, many=True)
        self.curr_data_paths = []
        for task in tasks:
            for data in task.datas:
                self.curr_data_paths.append(data.path)
        # print("Current data paths", self.curr_data_paths)

        self.project = Project._get(project_id=project.project_id)

    def populate_label_colors(self):
        labels = Label._get(project_id=self.project.project_id, many=True)
        for lab in labels:
            if lab.color is None:
                lab.color = rand_color([l.color for l in labels])
        db.session.commit()

    def add_label(self, name: str, color: str = None, commit=False):
        if name is None or len(name) == 0:
            return
        if color is None:
            color = rand_color([l.color for l in self.project.labels])
        label = Label(
            id=self.label_max_id + 1,
            project_id=self.project.project_id,
            name=name,
            color=color,
        )
        self.project.labels.append(label)
        if commit:
            db.session.commit()
        self.label_max_id += 1
        return label

    def add_task(self, datas: list, annotations: list = None, split: int = None):
        """Add one task to project.
        ATTENTION: to be more efficient, this method WONT connmit! make sure you invoke db.session.commit() after adding all tasks

        Parameters
        ----------
        datas : list. each item is a dict, path is required, specifying full or relative path to project.data_dir. Others are optional
            [{"path": 'path1'}, {"path" : 'path2', "size": [1024, 768, 3]}, ...]
        annotations : list
            [
                [ // labels for path1
                    {
                        "label_name": "",
                        "result": "", // optional, default to ""
                        "color": "" // optional, new label will be given a randon color
                    },
                    {
                        "label_name": "",
                        "result": "",
                        "color": ""
                    }
                ],
                [ // labels for path2
                    {
                        "label_name": "",
                        "result": "", [optional, default to ""]
                        "color": ""
                    },
                    {
                        "label_name": "",
                        "result": "", [optional, default to ""]
                        "color": ""
                    }
                ],
                ...
            ]
        split: int. the split set this task is in. If not passed will attempt to find in the three list files. If not found default to 0 (training set). 0, 1, 2-> train, val, test
        """
        project = self.project
        assert len(datas) != 0, "can't add task without data"
        print(datas, project.data_dir)
        # TODO: check abs path
        for idx in range(len(datas)):
            if osp.isabs(datas[idx]['path']):
                datas[idx]['path'] = osp.relpath(datas[idx]['path'], project.data_dir)
        
        # 1. find task split
        if split is None:
            split_idx = 0
            for idx, split in enumerate(self.split):
                if datas[0]["path"] in split:
                    split_idx = idx
                    break
        else:
            split_idx = split

        task = Task(project_id=project.project_id, set=split_idx)

        def get_label(name):
            for lab in project.labels:
                if lab.name == name:
                    return lab
            return None

        if annotations is None:
            annotations = []
        while len(annotations) < len(datas):
            annotations.append([])

        for anns, data_record in zip(annotations, datas):
            # 2. add data record
            data = Data(**data_record)
            task.datas.append(data)
            total_anns = 0

            # 3. add data's annotations
            for ann in anns:
                if len(ann.get("label_name", "")) == 0:
                    continue
                # BUG: multiple labels under same label_name can exist
                label = get_label(ann["label_name"])
                if label is None:
                    label = self.add_label(ann["label_name"], ann.get("color"), commit=True)
                del ann['label_name']
                ann = Annotation(
                    label_id=label.label_id,
                    project_id=project.project_id,
                    **ann
                )
                task.annotations.append(ann) # TODO: remove
                data.annotations.append(ann)
                total_anns += 1
            print(
                f"==== {data_record['path']} with {total_anns} annotation(s) imported to set {split_idx} ===="
            )

        db.session.add(task)

    def label_id2name(self, label_id):
        for label in self.project.labels:
            if label.id == label_id:
                return label.name
        return None

    def read_split(self, data_dir=None, delimiter=" "):
        if data_dir is None:
            data_dir = self.project.data_dir

        sets = []
        split_names = ["train_list.txt", "val_list.txt", "test_list.txt"]
        for split_name in split_names:
            split_path = osp.join(data_dir, split_name)
            paths = []
            if osp.exists(split_path):
                paths = open(split_path, "r").readlines()
                paths = [p.strip() for p in paths if len(p.strip()) != 0]
                paths = [p.split(delimiter)[0] for p in paths]
            sets.append(set(paths))
        return sets

    def export_split(self, export_dir, tasks, new_paths, delimiter=" "):
        set_names = ["train_list", "val_list", "test_list"]
        set_files = [open(osp.join(export_dir, f"{n}.txt"), "w") for n in set_names]
        for task, task_new_paths in zip(tasks, new_paths):
            for data, new_path in zip(task.datas, task_new_paths):
                label_ids = []
                for ann in data.annotations:
                    label_ids.append(ann.label.id - 1)
                if len(label_ids) == 0:
                    continue
                label_ids = [str(id) for id in label_ids]
                print(new_path + delimiter + delimiter.join(label_ids), file=set_files[task.set])

        for f in set_files:
            f.close()

    # TODO: seperate label file path from label dir
    def import_label_names(self, label_names_path, delimiter=" "):
        if label_names_path is None or not osp.exists(label_names_path):
            return
        labels = open(label_names_path, "r").readlines()
        labels = [l.strip() for l in labels if len(l.strip()) != 0]
        labels = [l.split(delimiter) for l in labels]
        current_labels = Label._get(project_id=self.project.project_id, many=True)
        current_labels = [l.name for l in current_labels]
        for label in labels:
            if len(label) > 2:
                raise RuntimeError(
                    f"Each line in labels.txt should contain at most 1 delimiter, after split got {label}"
                )
            if label[0] not in current_labels:
                print("==== Adding label", label, "====")
                self.add_label(*label)
        db.session.commit()

    def export_label_names(self, label_names_path: str, project_id: int = None):
        if project_id is None:
            project_id = self.project.project_id

        labels = Label._get(project_id=project_id, many=True)
        labels.sort(key=lambda l: l.id)
        with open(label_names_path, "w") as f:
            for lab in labels:
                print(lab.name, file=f)
        return labels

    # TODO: add total imported count
    def default_importer(
        self, data_dir=None, filters={"exclude_prefix": ["."], "include_postfix": image_extensions}
    ):
        if data_dir is None:
            data_dir = self.project.data_dir

        for data_path in listdir(data_dir, filters):
            split = 0  # TODO: test this
            for idx, set in enumerate(self.split):
                if data_path in set:
                    split = idx
            self.add_task([data_path], split=split)
        db.session.commit()

    def create_warning(self, dir):
        warning_path = osp.join(dir, "pplabel.warning")
        if not osp.exists(warning_path):
            print(
                "PP Label is using files stored under this folder!\nChanging file in this folder may cause issues.",
                file=open(warning_path, "w"),
            )

    def remove_warning(self, dir):
        warning_path = osp.join(dir, "pplabel.warning")
        if osp.exists(warning_path):
            os.remove(warning_path)
