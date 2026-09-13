import unittest
from agent.profile.repository import ProfileRepository
from agent.profile.proposals import ProfileProposal
from agent.profile.card_renderer import render_chara_card

class ProfileEndToEndTests(unittest.TestCase):
    @unittest.skipUnless(__import__('os').getenv('TWINLOOP_TEST_DATABASE_URL'), 'Set TWINLOOP_TEST_DATABASE_URL')
    def test_initialize_render_memory_evidence(self):
        r = ProfileRepository()
        init = r.initialize_avatar(user_id='00000000-0000-0000-0000-000000000001', identity={'display_name':'联调用户','summary':'后端工程师','occupation':'后端工程师'}, personality={'scores':{'openness':.7},'style_tags':['理性']})
        card = render_chara_card('00000000-0000-0000-0000-000000000001')
        self.assertEqual(card['data']['extensions']['twin']['version_id'], init['version_id'])

if __name__ == '__main__': unittest.main()
