from sklearn.metrics import f1_score
from unittest import TestCase
import torch

from src.models.model import Model
from src.utils import get_dvc_dir


class IntegrationTestModelPt(TestCase):
    def test_model_pt(self):
        model_dir = get_dvc_dir("models")
        model_names = [m.stem for m in model_dir.glob("*.pt")]
        no_differences = True

        for model_name in model_names:
            model_ckpt = Model.load_from_checkpoint(model_dir / f"{model_name}.ckpt")
            model_ckpt.eval()
            model_pt = torch.jit.load(model_dir / f"{model_name}.pt")
            model_pt.eval()

            # Get validation set
            val = model_ckpt.get_dataset(
                subset="validation",
                normalizing_dict=model_ckpt.normalizing_dict,
                upsample=False,
                is_local_only=True,
                cache=False,
            )
            # Get tensors from validation set
            x = torch.stack([v[0] for v in val])
            y_true = torch.stack([v[1] for v in val])

            # Feed tensors into both models
            with torch.no_grad():
                y_pred_ckpt = model_ckpt(x)[1].numpy()
                y_pred_pt = model_pt(x)[1].numpy()

            y_pred_ckpt_binary = y_pred_ckpt > 0.5
            y_pred_pt_binary = y_pred_pt > 0.5

            ckpt_f1 = round(f1_score(y_true=y_true, y_pred=y_pred_ckpt_binary), 4)
            pt_f1 = round(f1_score(y_true=y_true, y_pred=y_pred_pt_binary), 4)

            print("---------------------------------------------")
            print(model_name)

            # F1 score check
            if ckpt_f1 == pt_f1:
                print(f"\u2714 CKPT F1 == PT F1 == {pt_f1}")
            else:
                no_differences = False
                print(f"\u2716 CKPT F1: {ckpt_f1} != PT F1 {pt_f1}")

            if (y_pred_ckpt_binary == y_pred_pt_binary).all():
                print("\u2714 CKPT binary preds == PT binary preds")
            else:
                no_differences = False
                total = len(y_pred_ckpt_binary)
                diff = len(y_pred_ckpt_binary[y_pred_ckpt_binary != y_pred_pt_binary])
                print(f"\u2716 {diff}/{total} binary predictions don't match")

            if (y_pred_ckpt == y_pred_pt).all():
                print("\u2714 CKPT preds == PT preds")
            else:
                no_differences = False
                total = len(y_pred_ckpt)
                diff = len(y_pred_ckpt[y_pred_ckpt != y_pred_pt])
                print(f"\u2716 {diff}/{total} predictions don't match")

        self.assertTrue(no_differences, "Some ckpt and pt models don't match, check logs.")