import torch
import torch.onnx
import argparse

from backbone.model_irse import IR_50


def export(checkpoint_path, output_path):

    model = IR_50([112, 112])
    model.load_state_dict(torch.load(checkpoint_path, map_location="cpu"))
    model.eval()

    dummy_input = torch.randn(1, 3, 112, 112)

    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        input_names=["input"],
        output_names=["embedding"],
        opset_version=11,
        dynamic_axes={"input": {0: "batch_size"}}
    )

    print(f"Exported ONNX model to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)

    args = parser.parse_args()

    export(args.checkpoint, args.output)