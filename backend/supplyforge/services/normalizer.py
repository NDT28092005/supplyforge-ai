import unicodedata
import re


class VietnameseNormalizer:
    @staticmethod
    def strip_accents(input_str):
        if not input_str:
            return ""
        # Replace đ/Đ
        replaced = re.sub(r'đ', 'd', input_str)
        replaced = re.sub(r'Đ', 'D', replaced)
        # NFD decompose
        decomposed = unicodedata.normalize('NFD', replaced)
        # Remove combining marks
        stripped = "".join([c for c in decomposed if not unicodedata.combining(c)])
        return stripped.lower()


class Levenshtein:
    @staticmethod
    def distance(a, b):
        if a is None:
            a = ""
        if b is None:
            b = ""
        n, m = len(a), len(b)
        if n == 0:
            return m
        if m == 0:
            return n

        prev = list(range(m + 1))
        curr = [0] * (m + 1)

        for i in range(1, n + 1):
            curr[0] = i
            ca = a[i - 1]
            for j in range(1, m + 1):
                cost = 0 if ca == b[j - 1] else 1
                curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            prev = list(curr)

        return prev[m]
