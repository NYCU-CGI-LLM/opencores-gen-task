import openai
from typing import Optional
from openai.types.chat import ChatCompletion
import os
import PyPDF2
import argparse
import re
import weave

weave.init('opencores-gen-task')


def clean_and_compress_text(text: str) -> str:
    """
    清理和壓縮文字內容，移除不必要的字符和空白
    """
    # 移除多餘的空白字符
    text = ' '.join(text.split())

    # 移除重複的標點符號
    text = re.sub(r'[.]{3,}', '...', text)
    text = re.sub(r'[-]{3,}', '---', text)
    text = re.sub(r'[=]{3,}', '===', text)

    # 移除常見的頁眉頁腳模式
    text = re.sub(r'Page \d+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\d+/\d+', '', text)
    text = re.sub(r'©.*?\d{4}', '', text)

    # 移除多餘的特殊字符
    text = re.sub(
        r'[^\w\s\.\,\;\:\!\?\(\)\[\]\{\}\-\+\=\<\>\&\|\@\#\$\%\^\*\/\\]', ' ',
        text)

    # 移除多餘的數字序列（可能是頁碼或參考編號）
    text = re.sub(r'\b\d{5,}\b', '', text)

    # 壓縮多個空格為單一空格
    text = re.sub(r'\s+', ' ', text)

    # 移除行首行尾空白
    text = text.strip()

    return text


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    從 PDF 檔案中提取文字內容並進行壓縮清理
    """
    try:
        text = ""
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)

            # 遍歷所有頁面並提取文字
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                page_text = page.extract_text()

                # 清理每頁的文字
                cleaned_page_text = clean_and_compress_text(page_text)
                if cleaned_page_text:  # 只添加非空內容
                    text += cleaned_page_text + " "

        # 最終清理整個文字內容
        final_text = clean_and_compress_text(text)

        # 如果文字太長，進行進一步壓縮
        if len(final_text) > 15000:  # 約 3000-4000 tokens
            print(f"文字內容過長 ({len(final_text)} 字元)，進行進一步壓縮...")
            # 保留前 12000 字元和後 3000 字元
            final_text = final_text[:12000] + "\n...[內容已壓縮]...\n" + final_text[
                -3000:]

        return final_text

    except FileNotFoundError:
        print(f"錯誤：找不到 PDF 檔案 '{pdf_path}'")
        return ""
    except Exception as e:
        print(f"提取 PDF 文字時發生錯誤: {e}")
        return ""


def extract_verilog_from_dir(source_dir: str) -> str:
    """
    Read all Verilog files (.v, .sv) from the given directory and concatenate their contents.
    """
    verilog_text = ""
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(('.v', '.sv')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        verilog_text += f"\n// {file_path}\n"
                        verilog_text += f.read() + "\n"
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
    return verilog_text


@weave.op()
def call_api(prompt: str) -> Optional[ChatCompletion]:
    assert model is not None, "OPENAI_MODEL 未設定"
    try:
        response = openai.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": prompt
            }],
            response_format={"type": "json_object"})
        return response
    except Exception as e:
        print(f"API 呼叫失敗: {e}")
        return None


def estimate_tokens(text: str) -> int:
    """
    粗略估算文字的 token 數量 (1 token ≈ 4 字元)
    """
    return len(text) // 4


def main(pdf_path: str, source_dir: str, prompt: str):
    print(f"開始提取 PDF 文字內容：{pdf_path}")
    pdf_text = extract_text_from_pdf(pdf_path)

    print(f"開始讀取 Verilog source code：{source_dir}")
    verilog_text = extract_verilog_from_dir(source_dir)

    if not pdf_text:
        print("警告：PDF 文字提取失敗或為空")
    if not verilog_text:
        print("警告：未讀取到任何 Verilog source code")

    # Combine PDF and source code into the prompt
    full_prompt = (f"{prompt}\n\n"
                   "[Specification PDF Content]\n"
                   f"{pdf_text}\n\n"
                   "[Verilog Source Code]\n"
                   f"{verilog_text}")

    print(f"估算 prompt 文字 tokens: ~{estimate_tokens(full_prompt)}")
    print("呼叫 OpenAI API...")
    result = call_api(full_prompt)
    if result is not None:
        print("API 回應成功：")

        # 提取實際的 JSON 內容
        json_content = result.choices[0].message.content

        # 創建 generated 目錄
        os.makedirs("generated", exist_ok=True)

        # 提取 PDF 檔名（不包含 .pdf 後綴）
        pdf_filename = os.path.basename(pdf_path)
        if pdf_filename.lower().endswith('.pdf'):
            pdf_filename = pdf_filename[:-4]  # 移除 .pdf 後綴

        # 生成輸出檔案路徑
        output_filename = f"{pdf_filename}.json"  # 改為 .json 副檔名
        output_path = os.path.join("generated", output_filename)

        # 寫入檔案
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(json_content or '')
            print(f"JSON 內容已儲存至：{output_path}")
        except Exception as e:
            print(f"儲存檔案時發生錯誤：{e}")
    else:
        print("API 回傳為 None")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-path", type=str, required=True)
    parser.add_argument("--source-dir", type=str, required=True)
    args = parser.parse_args()

    # 設定 OpenAI API
    openai.api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")

    if not openai.api_key:
        print("錯誤：請設定 OPENAI_API_KEY 環境變數")
        exit(1)

    if not model:
        print("錯誤：請設定 OPENAI_MODEL 環境變數")
        exit(1)

    # prompt
    prompt = """
You are an experienced Verilog engineer. You will be provided with both a specification PDF and the final Verilog source code. Your task is to analyze and break down the requirements into a comprehensive, hierarchical task structure that accurately reflects both the specification and the actual code implementation. The goal is to produce a detailed, implementation-level task breakdown that can guide project management, code review, and verification planning.

Requirements:
- Analyze both the specification PDF and the Verilog source code.
- Identify all major functional modules and components (as described in the spec and as implemented in the code).
- For each module, break down into detailed sub-tasks at the implementation level.
- Support up to three levels of sub-modules (i.e., modules may contain sub-modules, which may themselves contain sub-modules, up to three levels deep).
- Establish clear hierarchical relationships between modules and sub-modules.
- Define module-level task descriptions with technical specifications.
- Consider dependencies and interfaces between different modules.
- Ensure the task breakdown matches the actual code structure and implementation.

Please return your analysis in the following JSON format:

{
  "project_overview": {
    "title": "Project title from the specification",
    "description": "Brief description of the overall project",
    "complexity_level": "Low/Medium/High"
  },
  "modules": [
    {
      "module_name": "Module name",
      "module_type": "e.g., Control Logic, Data Path, Interface, Memory Controller",
      "description": "Detailed description of the module functionality",
      "priority": "High/Medium/Low",
      "estimated_complexity": "Simple/Moderate/Complex",
      "interfaces": {
        "inputs": ["list of input signals/ports"],
        "outputs": ["list of output signals/ports"],
        "parameters": ["list of parameters if any"]
      },
      "tasks": [
        {
          "task_id": "unique identifier",
          "task_name": "Specific implementation task",
          "description": "Detailed task description",
          "dependencies": ["list of dependent task_ids"],
          "deliverables": ["what needs to be delivered"],
          "verification_requirements": ["how to verify this task"]
        }
      ],
      "sub_modules": [
        {
          "module_name": "Sub-module name (level 2)",
          "description": "Sub-module functionality",
          "tasks": [
            {
              "task_id": "unique identifier",
              "task_name": "Implementation task",
              "description": "Task details",
              "dependencies": ["dependencies"]
            }
          ],
          "sub_modules": [
            {
              "module_name": "Sub-module name (level 3)",
              "description": "Sub-sub-module functionality",
              "tasks": [
                {
                  "task_id": "unique identifier",
                  "task_name": "Implementation task",
                  "description": "Task details",
                  "dependencies": ["dependencies"]
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "integration_tasks": [
    {
      "task_id": "integration task identifier",
      "task_name": "Integration task name",
      "description": "Integration requirements (e.g., how to connect and verify multiple modules together, including sub-modules if necessary)",
      "involved_modules": ["list of modules and/or sub-modules to integrate (specify full path if nested)"],
      "verification_plan": "How to verify the integration (e.g., top-level simulation, interface checks, etc.)"
    }
  ],
  "verification_strategy": {
    "testbench_requirements": ["list of testbenches needed (specify for modules and sub-modules as appropriate)"],
    "simulation_scenarios": ["list of test scenarios, including corner cases and integration flows"],
    "coverage_requirements": ["coverage metrics to achieve, e.g., code, functional, interface coverage"]
  }
}

Notes:
- All task_ids must be unique across the entire project, including all module and sub-module levels.
- Dependencies should be clearly specified using task_ids.
- Module interfaces must be well-defined.
- The hierarchy should reflect logical and implementation order, supporting up to three levels of sub-modules.
- Technical complexity should be realistically assessed.
- The analysis and task breakdown must be consistent with the actual Verilog code provided.
- Respond ONLY with the JSON structure, no additional text.
"""

    # 檢查 PDF 檔案是否存在
    if not os.path.exists(args.spec_path):
        print(f"錯誤：PDF 檔案 '{args.spec_path}' 不存在")
        print("請確保 PDF 檔案位於正確的路徑，或修改 pdf_path 變數")
        exit(1)

    main(args.spec_path, args.source_dir, prompt)
