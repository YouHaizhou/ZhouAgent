from __future__ import annotations
from dataclasses import dataclass,field
import json,re
from typing import Callable,Generator,Iterator,Literal
import httpx
from .config import AppConfig
from .errors import ApiRequestError
TurnEventType=Literal["reasoning_delta","reasoning_done","reasoning_summary","tool_call","tool_result","answer_delta","answer_done"]
FINAL_RESPONSE_FORMAT_INSTRUCTION="""当你最终直接回答用户时，必须严格只输出以下 XML 结构，不要输出任何额外前后缀：
<final_response>
<answer>给用户看的最终回答</answer>
<reasoning_summary>供系统写入 turns.jsonl 的中文摘要，保留目标、关键步骤、工具调用和结论，避免空话，长度控制在 120-220 字左右</reasoning_summary>
</final_response>
如果当前轮需要调用工具，可以先发起工具调用；当你拿到工具结果并最终回答时，仍必须使用上述 XML 结构。"""
ANSWER_OPEN="<answer>";ANSWER_CLOSE="</answer>";SUMMARY_OPEN="<reasoning_summary>";SUMMARY_CLOSE="</reasoning_summary>"
@dataclass(slots=True)
class TurnEvent:type:TurnEventType;text:str="";name:str="";arguments:str="";result:str=""
@dataclass(slots=True)
class ToolCallState:id:str="";name:str="";arguments:str=""
@dataclass(slots=True)
class StreamRoundResult:content:str="";reasoning:str="";reasoning_summary:str="";raw_content:str="";tool_calls:list[dict[str,object]]=field(default_factory=list)
@dataclass(slots=True)
class FinalResponseParts:answer:str="";reasoning_summary:str=""
class FinalResponseStreamParser:
    def __init__(self)->None:self.pending="";self.in_answer=False
    def push(self,text:str)->str:
        if not text:return ""
        self.pending+=text;out:list[str]=[]
        while True:
            if not self.in_answer:
                idx=self.pending.find(ANSWER_OPEN)
                if idx==-1:
                    keep=max(0,len(ANSWER_OPEN)-1);self.pending=self.pending[-keep:] if keep else "";break
                self.pending=self.pending[idx+len(ANSWER_OPEN):];self.in_answer=True;continue
            close_idx=self.pending.find(ANSWER_CLOSE)
            if close_idx==-1:
                safe=max(0,len(self.pending)-(len(ANSWER_CLOSE)-1))
                if safe:out.append(self.pending[:safe]);self.pending=self.pending[safe:]
                break
            out.append(self.pending[:close_idx]);self.pending=self.pending[close_idx+len(ANSWER_CLOSE):];self.in_answer=False
        return "".join(out)
    def finish(self)->str:
        if self.in_answer and self.pending:text=self.pending;self.pending="";self.in_answer=False;return text
        self.pending="";self.in_answer=False;return ""
ToolExecutor=Callable[[str,str],str]
@dataclass(slots=True)
class LlmClient:
    config:AppConfig;http_client:httpx.Client
    def __init__(self,config:AppConfig)->None:self.config=config;self.http_client=httpx.Client(timeout=60.0)
    def respond_turn(self,system_prompt:str,messages:list[dict[str,object]],tools:list[dict[str,object]],tool_executor:ToolExecutor|None=None)->Iterator[TurnEvent]:
        if tools and tool_executor is not None:yield from self.chat_with_tools(system_prompt,messages,tools,tool_executor);return
        yield from self.chat_once_with_reasoning(system_prompt,messages)
    def chat_once_with_reasoning(self,system_prompt:str,messages:list[dict[str,object]])->Iterator[TurnEvent]:yield from self._stream_round(build_request_messages(system_prompt,messages),[],stream_answer_immediately=True)
    def chat_with_tools(self,system_prompt:str,messages:list[dict[str,object]],tools:list[dict[str,object]],tool_executor:ToolExecutor)->Iterator[TurnEvent]:
        conversation=build_request_messages(system_prompt,messages)
        while True:
            round_result=yield from self._stream_round(conversation,tools,stream_answer_immediately=False)
            if not round_result.tool_calls:return
            conversation.append(build_assistant_message(round_result.raw_content,round_result.reasoning,round_result.tool_calls))
            for tool_call in round_result.tool_calls:
                function=tool_call.get("function") or {}
                if not isinstance(function,dict):continue
                tool_name=str(function.get("name") or "").strip();arguments=str(function.get("arguments") or "{}");tool_call_id=str(tool_call.get("id") or "")
                yield TurnEvent(type="tool_call",name=tool_name,arguments=arguments)
                tool_output=tool_executor(tool_name,arguments)
                yield TurnEvent(type="tool_result",name=tool_name,arguments=arguments,result=tool_output)
                conversation.append({"role":"tool","tool_call_id":tool_call_id,"content":tool_output})
    def _stream_round(self,messages:list[dict[str,object]],tools:list[dict[str,object]],stream_answer_immediately:bool)->Generator[TurnEvent,None,StreamRoundResult]:
        payload:dict[str,object]={"model":self.config.model,"stream":True,"messages":messages}
        if tools:payload["tools"]=tools
        content_parts:list[str]=[];reasoning_parts:list[str]=[];tool_call_states:dict[int,ToolCallState]={};answer_parser=FinalResponseStreamParser();emitted_reasoning=False;emitted_answer=False
        try:
            with self.http_client.stream("POST",self.config.chat_completions_url,headers={"Authorization":f"Bearer {self.config.api_key}"},json=payload) as response:
                response.raise_for_status()
                for data in self._iter_sse_payloads(response):
                    choices=data.get("choices") or []
                    if not choices:continue
                    choice=choices[0] or {};delta=choice.get("delta") or {}
                    if not isinstance(delta,dict):continue
                    reasoning_delta=extract_delta_text(delta.get("reasoning_content")) or extract_delta_text(delta.get("reasoning"))
                    if reasoning_delta:reasoning_parts.append(reasoning_delta);emitted_reasoning=True;yield TurnEvent(type="reasoning_delta",text=reasoning_delta)
                    content_delta=extract_content_delta(delta.get("content"))
                    if content_delta:
                        content_parts.append(content_delta)
                        if stream_answer_immediately:
                            answer_delta=answer_parser.push(content_delta)
                            if answer_delta:emitted_answer=True;yield TurnEvent(type="answer_delta",text=answer_delta)
                    merge_tool_call_deltas(tool_call_states,delta.get("tool_calls"))
            if emitted_reasoning:yield TurnEvent(type="reasoning_done")
            raw_content="".join(content_parts).strip();parts=parse_final_response_parts(raw_content)
            if stream_answer_immediately:
                trailing=answer_parser.finish()
                if trailing:emitted_answer=True;yield TurnEvent(type="answer_delta",text=trailing)
            elif parts.answer and not tool_call_states:yield TurnEvent(type="answer_delta",text=parts.answer);emitted_answer=True
            if parts.reasoning_summary:yield TurnEvent(type="reasoning_summary",text=parts.reasoning_summary)
            if emitted_answer:yield TurnEvent(type="answer_done")
            return StreamRoundResult(content=parts.answer,reasoning="".join(reasoning_parts).strip(),reasoning_summary=parts.reasoning_summary,raw_content=raw_content,tool_calls=build_tool_calls(tool_call_states))
        except httpx.HTTPStatusError as exc:
            body=exc.response.text if exc.response is not None else "无法读取错误响应";raise ApiRequestError(f"HTTP {exc.response.status_code}: {body}") from exc
        except httpx.HTTPError as exc:raise ApiRequestError(f"请求模型接口失败: {exc}") from exc
    def _iter_sse_payloads(self,response:httpx.Response)->Iterator[dict[str,object]]:
        for line in response.iter_lines():
            if not line:continue
            data=line[5:].strip() if line.startswith("data:") else line.strip()
            if not data or data=="[DONE]":continue
            try:payload=json.loads(data)
            except json.JSONDecodeError:continue
            if isinstance(payload,dict):yield payload
    def close(self)->None:self.http_client.close()
def build_request_messages(system_prompt:str,messages:list[dict[str,object]])->list[dict[str,object]]:return [{"role":"system","content":f"{system_prompt}\n\n{FINAL_RESPONSE_FORMAT_INSTRUCTION}"},*messages]
def build_assistant_message(content:str,reasoning:str,tool_calls:list[dict[str,object]])->dict[str,object]:
    assistant_message:dict[str,object]={"role":"assistant","content":content,"tool_calls":tool_calls}
    if reasoning:assistant_message["reasoning_content"]=reasoning
    return assistant_message
def parse_final_response_parts(content:str)->FinalResponseParts:
    text=content.strip()
    if not text:return FinalResponseParts()
    answer=extract_tag_content(text,ANSWER_OPEN,ANSWER_CLOSE);summary=extract_tag_content(text,SUMMARY_OPEN,SUMMARY_CLOSE)
    if answer or summary:return FinalResponseParts(answer=normalize_inline_text(answer),reasoning_summary=normalize_inline_text(summary))
    return FinalResponseParts(answer=normalize_inline_text(text),reasoning_summary="")
def extract_tag_content(text:str,open_tag:str,close_tag:str)->str:
    match=re.search(re.escape(open_tag)+r"([\s\S]*?)"+re.escape(close_tag),text)
    return match.group(1).strip() if match else ""
def normalize_inline_text(text:str)->str:return " ".join(str(text or "").split()).strip()
def merge_tool_call_deltas(states:dict[int,ToolCallState],tool_calls:object)->None:
    if not isinstance(tool_calls,list):return
    for item in tool_calls:
        if not isinstance(item,dict):continue
        index=int(item.get("index") or 0);state=states.setdefault(index,ToolCallState())
        if item.get("id"):state.id+=str(item.get("id"))
        function=item.get("function") or {}
        if isinstance(function,dict):
            if function.get("name"):state.name+=str(function.get("name"))
            if function.get("arguments"):state.arguments+=str(function.get("arguments"))
def build_tool_calls(states:dict[int,ToolCallState])->list[dict[str,object]]:
    result:list[dict[str,object]]=[]
    for index in sorted(states):
        state=states[index];result.append({"id":state.id,"type":"function","function":{"name":state.name,"arguments":state.arguments or "{}"}})
    return result
def extract_content_delta(content:object)->str:
    if content is None:return ""
    if isinstance(content,str):return content
    if isinstance(content,list):
        parts:list[str]=[]
        for item in content:
            if isinstance(item,dict) and item.get("type")=="text" and item.get("text"):parts.append(str(item.get("text")))
        return "".join(parts)
    if isinstance(content,dict):
        text=content.get("text") or content.get("content")
        return str(text) if text else ""
    return str(content)
def extract_delta_text(value:object)->str:
    if value is None:return ""
    if isinstance(value,str):return value
    if isinstance(value,list):
        parts:list[str]=[]
        for item in value:
            if isinstance(item,str):parts.append(item)
            elif isinstance(item,dict):
                text=item.get("text") or item.get("content") or item.get("reasoning_content")
                if text:parts.append(str(text))
        return "".join(parts)
    if isinstance(value,dict):
        text=value.get("text") or value.get("content") or value.get("reasoning_content")
        return str(text) if text else ""
    return str(value)
