import io
from pypdf import PdfReader
from docx import Document
from fastapi import HTTPException

# Service 파일은 Java/Spring Boot의 Service Layer와 비슷합니다.
# 비즈니스 로직이나 외부 라이브러리 연동(여기서는 파일 파싱)을 담당합니다.

class ResumeParserService:
    def extract_text_from_pdf(self, file_content: bytes) -> str:
        """PDF 파일에서 텍스트를 추출합니다."""
        try:
            reader = PdfReader(io.BytesIO(file_content))
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            if not text.strip():
                raise HTTPException(status_code=400, detail="PDF 텍스트 추출 실패: 내용이 없거나 읽을 수 없는 형식입니다.")
            
            return text
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"PDF 텍스트 추출 중 오류 발생: {str(e)}")

    def extract_text_from_docx(self, file_content: bytes) -> str:
        """DOCX 파일에서 텍스트를 추출합니다."""
        try:
            doc = Document(io.BytesIO(file_content))
            text = "\n".join([para.text for para in doc.paragraphs])
            
            if not text.strip():
                raise HTTPException(status_code=400, detail="DOCX 텍스트 추출 실패: 내용이 없거나 읽을 수 없는 형식입니다.")
            
            return text
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"DOCX 텍스트 추출 중 오류 발생: {str(e)}")

    def parse_resume(self, file_content: bytes, filename: str) -> str:
        """파일 확장자에 따라 적절한 추출 방식을 선택합니다."""
        if filename.lower().endswith(".pdf"):
            return self.extract_text_from_pdf(file_content)
        elif filename.lower().endswith(".docx"):
            return self.extract_text_from_docx(file_content)
        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. PDF 또는 DOCX 파일을 업로드해주세요.")
