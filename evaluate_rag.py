import json
import math
from collections import Counter

# ==============================================================================
# Retrieval Evaluation Metrics
# ==============================================================================

def calculate_recall_at_k(retrieved, relevant, k=5):
    """Measures how many relevant documents were successfully retrieved."""
    retrieved_k = retrieved[:k]
    relevant_set = set(relevant)
    if not relevant_set: return 0.0
    hits = sum(1 for doc in retrieved_k if doc in relevant_set)
    return hits / len(relevant_set)

def calculate_precision_at_k(retrieved, relevant, k=5):
    """Measures how many of the retrieved documents are actually relevant."""
    retrieved_k = retrieved[:k]
    relevant_set = set(relevant)
    if not retrieved_k: return 0.0
    hits = sum(1 for doc in retrieved_k if doc in relevant_set)
    return hits / len(retrieved_k)

def calculate_mrr(retrieved, relevant):
    """Mean Reciprocal Rank: How far down the list the first relevant document is."""
    relevant_set = set(relevant)
    for i, doc in enumerate(retrieved):
        if doc in relevant_set:
            return 1.0 / (i + 1)
    return 0.0

def calculate_ndcg(retrieved, relevant, k=5):
    """Normalized Discounted Cumulative Gain: Quality of ranking."""
    relevant_set = set(relevant)
    dcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(retrieved), k)) if retrieved[i] in relevant_set)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant_set), k)))
    return dcg / idcg if idcg > 0 else 0.0

# ==============================================================================
# Generation Evaluation Metrics (Lexical)
# ==============================================================================

def exact_match(prediction, ground_truth):
    """Absolute exact match of strings."""
    return 1.0 if prediction.strip().lower() == ground_truth.strip().lower() else 0.0

def f1_score(prediction, ground_truth):
    """Token-level F1 Score overlap."""
    pred_tokens = prediction.strip().lower().split()
    truth_tokens = ground_truth.strip().lower().split()
    common = Counter(pred_tokens) & Counter(truth_tokens)
    num_same = sum(common.values())
    if num_same == 0: return 0.0
    precision = 1.0 * num_same / len(pred_tokens)
    recall = 1.0 * num_same / len(truth_tokens)
    return (2 * precision * recall) / (precision + recall)

# Optional Advanced Deep-Learning Libraries (Requires pip install rouge-score bert-score ragas)
def try_rouge_l(prediction, ground_truth):
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
        return scorer.score(ground_truth, prediction)['rougeL'].fmeasure
    except ImportError:
        return "Install rouge-score to calculate ROUGE-L"

def try_bert_score(predictions, ground_truths):
    try:
        if not predictions: return []
        from bert_score import score
        P, R, F1 = score(predictions, ground_truths, lang="en", verbose=False)
        return F1.tolist()
    except ImportError:
        return ["Install bert-score to calculate BERTScore" for _ in predictions]

# ==============================================================================
# RAG Specific Evaluation (RAGAS framework emulation / integration)
# ==============================================================================
def execute_ragas_evaluation(dataset_dict):
    """
    RAGAS / DeepEval Evaluation.
    This requires 'ragas' and a valid OpenAI/Gemini Key to run the LLM-as-a-judge eval.
    Returns dummy text if not installed, otherwise runs the actual RAGAS evaluator.
    """
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevance, context_precision, context_recall
        
        # Convert to HuggingFace Dataset required by RAGAS
        ds = Dataset.from_dict(dataset_dict)
        
        result = evaluate(
            ds,
            metrics=[
                faithfulness,
                answer_relevance,
                context_precision,
                context_recall,
            ],
        )
        return result
    except ImportError:
        return {
            "Faithfulness": "Requires pip install ragas",
            "Context_Precision": "Requires pip install ragas",
            "Context_Recall": "Requires pip install ragas",
            "Answer_Relevance": "Requires pip install ragas"
        }

# ==============================================================================
# Main Evaluator Pipeline
# ==============================================================================

def run_evaluation_pipeline(data_samples, k=5):
    """
    Runs the full evaluation pipeline and returns JSON.
    data_samples: List of dicts with:
        - question
        - answer (generated)
        - ground_truth
        - contexts (retrieved)
        - ground_truth_contexts
    """
    results = {
        "Retrieval_Evaluation": {"Recall@K": [], "Precision@K": [], "MRR": [], "nDCG": []},
        "Generation_Evaluation": {"ROUGE-L": [], "BLEU": "Requires nltk/sacrebleu", "BERTScore": [], "Exact_Match": [], "F1_Score": []},
        "RAG_Specific_Evaluation": {},
        "Recommended_Metrics": {}
    }

    predictions = []
    ground_truths = []
    ragas_dataset = {"question": [], "answer": [], "contexts": [], "ground_truth": []}

    for sample in data_samples:
        pred = sample.get("answer", "")
        truth = sample.get("ground_truth", "")
        retrieved = sample.get("contexts", [])
        relevant = sample.get("ground_truth_contexts", [])

        # Lists for advanced metrics
        predictions.append(pred)
        ground_truths.append(truth)
        
        # Ragas formatting
        ragas_dataset["question"].append(sample.get("question", ""))
        ragas_dataset["answer"].append(pred)
        ragas_dataset["contexts"].append(retrieved)
        ragas_dataset["ground_truth"].append(truth)

        # Calculate standard retrieval
        results["Retrieval_Evaluation"]["Recall@K"].append(calculate_recall_at_k(retrieved, relevant, k))
        results["Retrieval_Evaluation"]["Precision@K"].append(calculate_precision_at_k(retrieved, relevant, k))
        results["Retrieval_Evaluation"]["MRR"].append(calculate_mrr(retrieved, relevant))
        results["Retrieval_Evaluation"]["nDCG"].append(calculate_ndcg(retrieved, relevant, k))

        # Calculate standard generation
        results["Generation_Evaluation"]["Exact_Match"].append(exact_match(pred, truth))
        results["Generation_Evaluation"]["F1_Score"].append(f1_score(pred, truth))
        results["Generation_Evaluation"]["ROUGE-L"].append(try_rouge_l(pred, truth))

    # Calculate Batch metrics (BERT Score)
    results["Generation_Evaluation"]["BERTScore"] = try_bert_score(predictions, ground_truths)

    # Ragas Metrics
    ragas_eval = execute_ragas_evaluation(ragas_dataset)
    if isinstance(ragas_eval, dict):
        results["RAG_Specific_Evaluation"] = ragas_eval
    else:
        results["RAG_Specific_Evaluation"] = {
            "Faithfulness": ragas_eval.get('faithfulness', 0.0),
            "Context_Precision": ragas_eval.get('context_precision', 0.0),
            "Context_Recall": ragas_eval.get('context_recall', 0.0),
            "Answer_Relevance": ragas_eval.get('answer_relevance', 0.0)
        }

    # Average out lists for final output
    def avg(lst):
        nums = [x for x in lst if isinstance(x, (int, float))]
        return round(sum(nums)/len(nums), 4) if nums else lst[0] if lst else None

    final_report = {
        "Retrieval_Evaluation": {
            k: avg(v) for k, v in results["Retrieval_Evaluation"].items()
        },
        "Generation_Evaluation": {
            "ROUGE-L": avg(results["Generation_Evaluation"]["ROUGE-L"]),
            "BLEU": results["Generation_Evaluation"]["BLEU"],
            "BERTScore": avg(results["Generation_Evaluation"]["BERTScore"]),
            "Exact_Match": avg(results["Generation_Evaluation"]["Exact_Match"]),
            "F1_Score": avg(results["Generation_Evaluation"]["F1_Score"])
        },
        "RAG_Specific_Evaluation": results["RAG_Specific_Evaluation"]
    }

    # Build the Recommended Metrics Highlight
    final_report["Recommended_Metrics"] = {
        "Recall@K": final_report["Retrieval_Evaluation"]["Recall@K"],
        "BERTScore": final_report["Generation_Evaluation"]["BERTScore"],
        "ROUGE-L": final_report["Generation_Evaluation"]["ROUGE-L"],
        "Faithfulness": final_report["RAG_Specific_Evaluation"].get("Faithfulness", "N/A"),
        "Answer_Relevance": final_report["RAG_Specific_Evaluation"].get("Answer_Relevance", "N/A"),
        "Context_Precision": final_report["RAG_Specific_Evaluation"].get("Context_Precision", "N/A")
    }

    return json.dumps(final_report, indent=4)


# ==============================================================================
# Execution Example
# ==============================================================================
if __name__ == "__main__":
    sample_data = [
        {
            "question": "What is the penalty for dowry harassment?",
            "ground_truth": "Under Section 498A of the IPC, the penalty for dowry harassment is imprisonment for up to three years and a fine.",
            "answer": "Dowry harassment is punishable by up to 3 years in prison under Section 498A of the Indian Penal Code.",
            "contexts": [
                "Section 498A IPC deals with husbands or relatives subjecting a woman to cruelty.",
                "The punishment for Section 498A is imprisonment up to 3 years and a fine."
            ],
            "ground_truth_contexts": [
                "The punishment for Section 498A is imprisonment up to 3 years and a fine."
            ]
        }
    ]

    print("Running evaluations... (If packages are missing, placeholders will be returned)")
    output_json = run_evaluation_pipeline(sample_data, k=2)
    print("\n--- FINAL EVALUATION METRICS ---")
    print(output_json)
