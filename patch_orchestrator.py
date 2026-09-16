import re

with open("src/orchestrator.py", "r") as f:
    code = f.read()

# 1. Update update_progress definition
old_up = """    def update_progress(stage: int, stage_name: str, percent: int, message: str):
        print(f"[{stage}/5] ({percent}%) {stage_name}: {message}")
        if progress_callback:
            try:
                progress_callback(stage, stage_name, percent, message)
            except Exception as e:"""
            
new_up = """    def update_progress(stage: int, stage_name: str, percent: int, message: str, inter_data: dict = None):
        print(f"[{stage}/5] ({percent}%) {stage_name}: {message}")
        if progress_callback:
            try:
                import inspect
                sig = inspect.signature(progress_callback)
                if 'inter_data' in sig.parameters:
                    progress_callback(stage, stage_name, percent, message, inter_data=inter_data)
                else:
                    progress_callback(stage, stage_name, percent, message)
            except Exception as e:"""

code = code.replace(old_up, new_up)

# 2. Add inter_data to Step 1 end
code = code.replace(
    'update_progress(1, "Sinh từ khoá", 20, f"Đã chuẩn bị xong {len(queries)} từ khoá.")',
    'update_progress(1, "Sinh từ khoá", 20, f"Đã chuẩn bị xong {len(queries)} từ khoá.", inter_data={"queries": queries})'
)

# 3. Add inter_data to Step 2 end
code = code.replace(
    'update_progress(2, "Cào dữ liệu Google Maps", 50, f"Cào thô hoàn tất: {raw_count} doanh nghiệp. Bắt đầu lọc rác sơ bộ...")',
    'update_progress(2, "Cào dữ liệu Google Maps", 50, f"Cào thô hoàn tất: {raw_count} doanh nghiệp. Bắt đầu lọc rác sơ bộ...", inter_data={"raw_count": raw_count, "raw_places": simplified_raw[:500]})'
)

# 4. Add inter_data to Step 3 end
code = code.replace(
    'print(f"    [BƯỚC 3 KẾT QUẢ] Sau lọc Heuristic còn lại {cand_count} ứng viên đủ điều kiện thẩm định (Đã lọc bỏ: {excl_count}).")',
    'print(f"    [BƯỚC 3 KẾT QUẢ] Sau lọc Heuristic còn lại {cand_count} ứng viên đủ điều kiện thẩm định (Đã lọc bỏ: {excl_count}).")\n    update_progress(3, "Lọc rác sơ bộ & Heuristic", 65, f"Xong lọc rác. Còn {cand_count} ứng viên.", inter_data={"candidates_count": cand_count, "excluded_count": excl_count, "candidates": candidates, "excluded": excluded_records[:200]})'
)

# 5. Add inter_data to Step 4 end
code = code.replace(
    'update_progress(4, "Thẩm định Web/Mạng Xã Hội", 85, f"Hoàn tất thẩm định {len(verdicts)} website. Đang phân loại tier...")',
    'update_progress(4, "Thẩm định Web/Mạng Xã Hội", 85, f"Hoàn tất thẩm định {len(verdicts)} website. Đang phân loại tier...", inter_data={"verdicts": verdicts, "reverify": reverify_list})'
)

with open("src/orchestrator.py", "w") as f:
    f.write(code)

print("Patched orchestrator.py")
