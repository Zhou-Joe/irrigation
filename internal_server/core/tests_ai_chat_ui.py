"""Wire-level regressions for the assistant activity and artifact UI."""
import json
from django.test import SimpleTestCase
from langchain_core.messages import AIMessageChunk, ToolMessage
from .ai_views import _events_from_chunk


class AssistantStreamTests(SimpleTestCase):
    def start(self, call, name='query_zones', message='message-1'):
        return AIMessageChunk(content='', id=message, tool_call_chunks=[{'name':name,'args':'{}','id':call,'index':0}])

    def test_index_zero_can_run_again_in_later_model_round(self):
        seen={}
        first=list(_events_from_chunk(self.start('call-1'),seen))
        list(_events_from_chunk(ToolMessage(content='{}',tool_call_id='call-1',name='query_zones'),seen))
        second=list(_events_from_chunk(self.start('call-2'),seen))
        self.assertEqual(first[0][1]['id'],'call-1')
        self.assertEqual(second[0][1]['id'],'call-2')

    def test_repeated_chunks_do_not_duplicate_tool_start(self):
        seen={};self.assertEqual(len(list(_events_from_chunk(self.start('call-1'),seen))),1)
        self.assertEqual(list(_events_from_chunk(self.start('call-1'),seen)),[])
        self.assertEqual(list(_events_from_chunk(self.start(None),seen)),[])

    def test_missing_provider_ids_can_run_again_after_result(self):
        seen={};self.assertEqual(len(list(_events_from_chunk(self.start(None),seen))),1)
        list(_events_from_chunk(ToolMessage(content='{}',tool_call_id='call-1',name='query_zones'),seen))
        self.assertEqual(len(list(_events_from_chunk(self.start(None),seen))),1)

    def test_tool_result_matches_its_actual_id_and_reports_failure(self):
        for content in ['{"error":"failed"}','{"exit_code":1}','{"success":false}']:
            events=list(_events_from_chunk(ToolMessage(content=content,tool_call_id='call-x',name='run_python_code'),{}))
            self.assertEqual(events[-1][1]['id'],'call-x')
            self.assertEqual(events[-1][1]['status'],'error')

    def test_list_or_malformed_tool_output_does_not_break_stream(self):
        for content in ['[]','null','not json','{"files":[null,"bad"]}']:
            events=list(_events_from_chunk(ToolMessage(content=content,tool_call_id='call-x',name='run_python_code'),{}))
            self.assertEqual(events[-1][0],'tool_end')

    def test_compiled_weekly_report_gets_a_download_card(self):
        file={'name':'week.docx','url':'/media/ai_workspaces/u1-abcd1234/week.docx','size':2048}
        events=list(_events_from_chunk(ToolMessage(content=json.dumps({'file':file}),tool_call_id='call-report',name='build_weekly_report'),{}))
        self.assertEqual(events[0],('file',file))

    def test_text_and_tool_events_in_one_chunk_are_both_preserved(self):
        chunk=self.start('call-1');chunk.content='我来查询。'
        events=list(_events_from_chunk(chunk,{}))
        self.assertEqual([event[0] for event in events],['tool_start','token'])
        self.assertEqual(events[-1][1]['text'],'我来查询。')
