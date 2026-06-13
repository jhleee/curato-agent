import re
from collections import Counter

class AutoLabeler:
    """
    군집 내 제목들에서 핵심 명사/엔티티를 추출하여
    LLM 없이도 1차 라벨을 생성합니다.
    """

    STOPWORDS_KO = {
        '것', '수', '이', '등', '및', '의', '가', '을', '를',
        '에', '서', '로', '으로', '한', '하는', '있다', '없다',
        '대해', '관해', '위해', '통해', '따라',
    }

    STOPWORDS_EN = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'this', 'that', 'it', 'in', 'on', 'at', 'for', 'with', 'to',
        'of', 'and', 'or', 'but', 'not', 'from',
    }

    def extract_keywords(self, titles: list[str], language: str = 'ko', top_n: int = 5) -> list[str]:
        """
        한국어: Kiwi 명사 추출 시도, 없으면 간단한 정규식 폴백
        영어: 대문자 시작 단어(고유명사) 및 빈도 상위 명사 추출
        """
        if language == 'ko':
            return self._extract_ko(titles, top_n)
        else:
            return self._extract_en(titles, top_n)

    def _extract_ko(self, titles: list[str], top_n: int) -> list[str]:
        try:
            from kiwipiepy import Kiwi
            kiwi = Kiwi()
            tokens = []
            for title in titles:
                result = kiwi.analyze(title)
                for sent in result:
                    for token in sent[0]:
                        if token.tag in ('NNG', 'NNP', 'SL') \
                                and len(token.form) >= 2 \
                                and token.form not in self.STOPWORDS_KO:
                            tokens.append(token.form)
        except ImportError:
            # Kiwi 없을 때 폴백: 2글자 이상 한글 명사 형태 추출
            tokens = []
            for title in titles:
                found = re.findall(r'[가-힣]{2,}', title)
                tokens.extend(w for w in found if w not in self.STOPWORDS_KO)

        counter = Counter(tokens)
        return [word for word, _ in counter.most_common(top_n)]

    def _extract_en(self, titles: list[str], top_n: int) -> list[str]:
        tokens = []
        for title in titles:
            # 대문자 시작 단어 (고유명사 가능성 높음)
            proper_nouns = re.findall(r'\b[A-Z][a-z]{1,}\b', title)
            tokens.extend(proper_nouns)
            # 소문자 단어 (불용어 제거)
            lower_words = re.findall(r'\b[a-z]{3,}\b', title.lower())
            tokens.extend(w for w in lower_words if w not in self.STOPWORDS_EN)

        counter = Counter(tokens)
        return [word for word, _ in counter.most_common(top_n)]

    def build_label(self, keywords: list[str]) -> str:
        """
        상위 키워드 최대 3개를 조합해 라벨 생성.
        """
        if not keywords:
            return "미분류 이슈"
        return " · ".join(keywords[:3])
