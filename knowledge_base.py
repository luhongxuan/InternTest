# knowledge_base.py
import ollama
import numpy as np

class ProcedureKnowledgeBase:
    """單純的向量檢索,不做規劃"""
    
    def __init__(self, procedures):
        self.procedures = procedures
        self.embeddings = {}
        self._build_index()
    
    def _get_embedding(self, text: str) -> np.ndarray:
        response = ollama.embeddings(
            model='nomic-embed-text',
            prompt=text
        )
        return np.array(response['embedding'])
    
    def _build_index(self):
        print("建立操作手冊索引...")
        for proc in self.procedures:
            use_when_str = ", ".join(proc.get('use_when', []))
            text = f"{proc['name']}. {proc.get('goal', '')}. 使用時機: {use_when_str}"
            self.embeddings[proc['id']] = self._get_embedding(text)
        print(f"完成,共 {len(self.procedures)} 個操作")
    
    def search(self, query: str, top_k: int = 5) -> list:
        """檢索所有相關的 procedures,回傳給 Agent 讓它自己規劃"""
        query_emb = self._get_embedding(query)
        
        scores = []
        for proc in self.procedures:
            score = self._cosine_similarity(query_emb, self.embeddings[proc['id']])
            scores.append((proc, score))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
    
    def get_all_procedures_summary(self) -> str:
        """給 Agent 看的手冊摘要"""
        summary = "【可用的操作手冊】\n\n"
        for proc in self.procedures:
            summary += f"◆ {proc['id']}: {proc['name']}\n"
            summary += f"  目標: {proc.get('goal', '')}\n"
            summary += f"  使用時機: {', '.join(proc.get('use_when', []))}\n"
            summary += f"  禁止使用時機: {', '.join(proc.get('do_not_use_when', []))}\n\n"
        return summary
    
    def get_procedure(self, procedure_id: str) -> dict:
        for proc in self.procedures:
            if proc['id'] == procedure_id:
                return proc
        return None
    
    def _cosine_similarity(self, a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))