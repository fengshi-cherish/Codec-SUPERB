import argparse
import json
import gc
import time
import numpy as np
from datasets import load_dataset, DownloadMode
from collections import defaultdict
from audiotools import AudioSignal
from codec.general import pad_arrays_to_match
from metrics import get_metrics
import psutil


def compute_metrics(entry, id_dict, max_duration):
    original_arrays, resynth_array = pad_arrays_to_match(entry['audio']['array'], id_dict[entry['id']])
    sampling_rate = entry['audio']['sampling_rate']
    original_signal = AudioSignal(original_arrays, sampling_rate)
    if original_signal.duration > max_duration:
        return None
    model_signal = AudioSignal(resynth_array, sampling_rate)
    metrics = get_metrics(original_signal, model_signal)
    return metrics


def batched_dataset(dataset, batch_size):
    batch = []
    for item in dataset:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def process_entry(entry, id_dict, metrics_results, max_duration):
    if isinstance(entry, dict):  # Single entry in streaming mode
        metrics = compute_metrics(entry, id_dict, max_duration)
        if metrics is not None:
            metrics_results.append(metrics)
    elif isinstance(entry, list):  # Batch of entries in batch mode
        for item in entry:
            metrics = compute_metrics(item, id_dict, max_duration)
            if metrics is not None:
                metrics_results.append(metrics)


def evaluate_dataset(dataset_name, mode, batch_size, specific_models=None, max_duration=120):
    start_time = time.time()  # Start time measurement
    print(f"Initial RAM used: {psutil.Process().memory_info().rss / (1024 * 1024):.2f} MB\n")

    c = load_dataset(dataset_name, streaming=(mode == 'streaming'))
    models = [key for key in c.keys() if key != "original"]

    result_data = {}
    for model in models:
        if specific_models is not None and model not in specific_models:
            continue
        print(f"Evaluating metrics for model: {model}")
        model_start_time = time.time()
        id_dict = {i['id']: i['audio']['array'] for i in c[model]}

        # Process dataset
        metrics_results = []
        dataset_iterable = c['original'] if mode == 'streaming' else batched_dataset(c['original'], batch_size)

        for entry in dataset_iterable:
            process_entry(entry, id_dict, metrics_results, max_duration)

        # Aggregate the metrics
        aggregated_metrics = defaultdict(list)
        for metrics in metrics_results:
            for k, v in metrics.items():
                aggregated_metrics[k].append(v)

        # Calculate and print average metrics
        model_result = {k: np.nanmean(v) if v else np.nan for k, v in aggregated_metrics.items()}
        result_data[model] = model_result
        del id_dict  # Release memory
        gc.collect()  # Explicitly invoke garbage collection
        print(f"RAM used after processing {model}: {psutil.Process().memory_info().rss / (1024 * 1024):.2f} MB")
        print(f"Time taken for {model}: {time.time() - model_start_time:.2f} seconds")
        print(model_result)
        print()

    print(f"Total execution time: {time.time() - start_time:.2f} seconds")
    print(f"Final RAM used: {psutil.Process().memory_info().rss / (1024 * 1024):.2f} MB")

    # Save results
    output_file_name = f"{dataset_name.replace('/', '_')}_evaluation_results.json"
    with open(output_file_name, 'w') as out_file:
        json.dump(result_data, out_file, indent=4)

    print(f"Results saved to {output_file_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Evaluate audio datasets.')
    parser.add_argument('--dataset', type=str, default="AudioDecBenchmark/librispeech_asr_dummy_synth",
                        help='Name of the dataset to evaluate')
    parser.add_argument('--mode', type=str, choices=['batch', 'streaming'], default='streaming',
                        help='Mode of dataset loading: batch or streaming')
    parser.add_argument('--batch_size', type=int, default=100,
                        help='Batch size for processing the dataset')
    parser.add_argument('--models', nargs='*', help='Specific models to evaluate')
    parser.add_argument('--max_duration', type=int, default=120,
                        help='Maximum duration of audio recordings in seconds')

    args = parser.parse_args()
    evaluate_dataset(args.dataset, args.mode, args.batch_size, args.models, args.max_duration)
