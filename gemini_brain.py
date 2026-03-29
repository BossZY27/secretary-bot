import json
import re
import os

from google import genai

# Configure Gemini client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.5-flash"


def extract_json(text: str):
    """Extract JSON from Gemini response, handling markdown code fences."""
    # Try to find JSON in code fences
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if match:
        text = match.group(1).strip()

    # Try to find JSON array or object
    for pattern in [r"(\[[\s\S]*\])", r"(\{[\s\S]*\})"]:
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    # Last resort: try parsing the whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def classify_intent(user_message: str) -> str:
    """Classify user's intent into: add, query_free, list, delete, or chat."""
    prompt = f"""คุณเป็นระบบจำแนกความตั้งใจของผู้ใช้ ตอบเป็นคำเดียวเท่านั้น

ข้อความ: "{user_message}"

จำแนกเป็นหนึ่งในนี้:
- add = ผู้ใช้ต้องการเพิ่มตารางงาน/นัด/กิจกรรม (เช่น "ประชุม 10 โมง", "พรุ่งนี้ไปหาหมอ")
- query_free = ผู้ใช้ถามเรื่องเวลาว่าง (เช่น "ว่างตอนไหน", "วันไหนว่าง")
- list = ผู้ใช้ต้องการดูตารางงาน (เช่น "วันนี้มีอะไรบ้าง", "ตารางสัปดาห์นี้")
- delete = ผู้ใช้ต้องการลบตารางงาน (เช่น "ยกเลิกนัด", "ลบประชุม")
- chat = อื่นๆ ที่ไม่เกี่ยวกับตารางงาน

ตอบแค่คำเดียว: add, query_free, list, delete, หรือ chat"""

    response = await client.aio.models.generate_content(
        model=MODEL, contents=prompt
    )
    result = response.text.strip().lower()

    valid_intents = ["add", "query_free", "list", "delete", "chat"]
    for intent in valid_intents:
        if intent in result:
            return intent
    return "chat"


async def parse_text_to_schedules(user_message: str, today: str) -> list[dict]:
    """Parse user's text into structured schedule data."""
    prompt = f"""คุณเป็นระบบแปลงข้อความเป็นตารางงาน วันนี้คือ {today}

ข้อความ: "{user_message}"

แปลงเป็น JSON array โดยแต่ละรายการมี:
- title: ชื่อกิจกรรม (string)
- date: วันที่ในรูปแบบ YYYY-MM-DD (ถ้าบอก "วันจันทร์" ให้ใช้วันจันทร์ถัดไป, "พรุ่งนี้" = วันถัดไป)
- start_time: เวลาเริ่ม HH:MM (24 ชั่วโมง, "10 โมง" = "10:00", "บ่าย 2" = "14:00", "ตีสอง" = "02:00")
- end_time: เวลาสิ้นสุด HH:MM (ถ้าไม่ระบุ ให้เดา 1 ชั่วโมงหลังเวลาเริ่ม)
- notes: หมายเหตุเพิ่มเติม (string หรือ null)

กฎ:
- วันที่ต้องเป็นอนาคตเสมอ (ยกเว้นระบุชัดว่าเป็นอดีต)
- ถ้าบอก "ทุกวันจันทร์" ให้สร้าง 4 รายการ (4 สัปดาห์ถัดไป)
- ถ้าข้อมูลไม่เพียงพอ ให้เดาตามบริบท

ตอบเป็น JSON array เท่านั้น ไม่ต้องอธิบาย"""

    response = await client.aio.models.generate_content(
        model=MODEL, contents=prompt
    )
    result = extract_json(response.text)

    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    return result


async def parse_image_to_schedules(image_bytes: bytes, today: str) -> list[dict]:
    """Extract schedules from an image using Gemini vision."""
    prompt = f"""คุณกำลังดูรูปภาพของตารางงาน/ตารางเรียน/ปฏิทิน วันนี้คือ {today}

อ่านทุกกิจกรรม/นัดหมายที่เห็นในรูป แล้วแปลงเป็น JSON array:
- title: ชื่อกิจกรรม
- date: วันที่ YYYY-MM-DD (ถ้าเห็นแค่วันในสัปดาห์ ให้ใช้สัปดาห์ปัจจุบันหรือสัปดาห์ถัดไป)
- start_time: เวลาเริ่ม HH:MM
- end_time: เวลาสิ้นสุด HH:MM
- notes: หมายเหตุ (null ถ้าไม่มี)

ถ้าอ่านรูปไม่ออกหรือไม่ใช่ตารางงาน ให้ตอบ: []

ตอบเป็น JSON array เท่านั้น"""

    from google.genai import types

    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

    response = await client.aio.models.generate_content(
        model=MODEL, contents=[prompt, image_part]
    )
    result = extract_json(response.text)

    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    return result


async def analyze_free_time(user_question: str, schedules: list[dict], today: str) -> str:
    """Analyze user's schedules and answer questions about free time."""
    schedules_text = json.dumps(schedules, ensure_ascii=False, indent=2) if schedules else "ไม่มีตารางงาน"

    prompt = f"""คุณเป็นเลขาส่วนตัว ตอบเป็นภาษาไทยแบบเป็นกันเอง

วันนี้: {today}
ตารางงานของผู้ใช้:
{schedules_text}

คำถาม: "{user_question}"

ตอบเรื่องเวลาว่าง/ตารางงานอย่างละเอียด ระบุช่วงเวลาที่ว่างชัดเจน
สมมติว่าเวลาทำงานปกติคือ 08:00-20:00 (ช่วงเวลานอกนี้ถือว่าเป็นเวลาส่วนตัว)
ถ้าไม่มีตารางงานเลย ให้บอกว่าว่างทั้งวัน"""

    response = await client.aio.models.generate_content(
        model=MODEL, contents=prompt
    )
    return response.text.strip()


async def chat_response(user_message: str, schedules: list[dict], today: str) -> str:
    """General secretary chat response."""
    schedules_text = json.dumps(schedules, ensure_ascii=False, indent=2) if schedules else "ไม่มีตารางงาน"

    prompt = f"""คุณเป็นเลขาส่วนตัวชื่อ "น้องเลขา" พูดภาษาไทยเป็นกันเอง สุภาพ

วันนี้: {today}
ตารางงานของผู้ใช้:
{schedules_text}

ข้อความ: "{user_message}"

ตอบในฐานะเลขาส่วนตัว ช่วยเรื่องตารางงาน แนะนำการจัดเวลา
ถ้าผู้ใช้ทักทาย ให้แนะนำว่าสามารถ:
- พิมพ์บอกนัดหมาย/ตารางงาน
- ส่งรูปตารางให้อ่าน
- ถามเวลาว่าง
- พิมพ์ /list ดูตารางทั้งหมด"""

    response = await client.aio.models.generate_content(
        model=MODEL, contents=prompt
    )
    return response.text.strip()


async def parse_delete_request(user_message: str, schedules: list[dict], today: str) -> list[int]:
    """Parse which schedules the user wants to delete."""
    if not schedules:
        return []

    schedules_text = json.dumps(schedules, ensure_ascii=False, indent=2)

    prompt = f"""วันนี้: {today}
ตารางงานของผู้ใช้:
{schedules_text}

ผู้ใช้พูดว่า: "{user_message}"

ผู้ใช้ต้องการลบตารางงานไหนบ้าง? ตอบเป็น JSON array ของ id (ตัวเลข) ที่ต้องการลบ
ถ้าไม่แน่ใจ ให้ตอบ []

ตอบเป็น JSON array เท่านั้น เช่น [1, 3, 5]"""

    response = await client.aio.models.generate_content(
        model=MODEL, contents=prompt
    )
    result = extract_json(response.text)

    if isinstance(result, list):
        return [int(x) for x in result if isinstance(x, (int, float))]
    return []
