import re
from collections import Counter
import math

def get_cosine(vec1, vec2):
    intersection = set(vec1.keys()) & set(vec2.keys())
    numerator = sum([vec1[x] * vec2[x] for x in intersection])
    
    sum1 = sum([vec1[x]**2 for x in vec1.keys()])
    sum2 = sum([vec2[x]**2 for x in vec2.keys()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)
    
    if not denominator:
        return 0.0
    else:
        return float(numerator) / denominator

def word2vec(word_list):
    return Counter(word_list)

def calculate_bow_similarity(text1, text2):
    t1 = re.sub(r'--- TRANG \d+ ---', '', text1)
    t2 = re.sub(r'--- TRANG \d+ ---', '', text2)
    
    # Split into words, remove punctuation, lowercase
    words1 = re.findall(r'\w+', t1.lower())
    words2 = re.findall(r'\w+', t2.lower())
    
    vec1 = word2vec(words1)
    vec2 = word2vec(words2)
    
    return get_cosine(vec1, vec2) * 100

def test():
    with open('content.md', 'r', encoding='utf-8') as f:
        local_text = f.read()
        
    # We need Gemini's output. Wait, I didn't save Gemini's output to a file in app_v2.py!
    # Let me just rewrite app_v2.py to use this better metric!
