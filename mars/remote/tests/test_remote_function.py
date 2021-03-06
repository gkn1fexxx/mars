# Copyright 1999-2020 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import defaultdict

import numpy as np

from mars import tensor as mt
from mars.remote import spawn, ExecutableTuple
from mars.session import new_session, Session
from mars.lib.mmh3 import hash as mmh3_hash
from mars.tests.core import TestBase, ExecutorForTest


class Test(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = ExecutorForTest('numpy')
        self.ctx, self.executor = self._create_test_context(self.executor)
        self.ctx.__enter__()

    def tearDown(self) -> None:
        self.ctx.__exit__(None, None, None)

    def testRemoteFunction(self):
        def f1(x):
            return x + 1

        def f2(x, y, z=None):
            return x * y * (z[0] + z[1])

        rs = np.random.RandomState(0)
        raw1 = rs.rand(10, 10)
        raw2 = rs.rand(10, 10)

        r1 = spawn(f1, raw1)
        r2 = spawn(f1, raw2)
        r3 = spawn(f2, (r1, r2), {'z': [r1, r2]})

        result = self.executor.execute_tileables([r3])[0]
        expected = (raw1 + 1) * (raw2 + 1) * (raw1 + 1 + raw2 + 1)
        np.testing.assert_almost_equal(result, expected)

        with self.assertRaises(TypeError):
            spawn(f2, (r1, r2), kwargs=())

        session = new_session()

        def f():
            assert Session.default.session_id == session.session_id
            return mt.ones((2, 3)).sum().to_numpy()

        self.assertEqual(spawn(f).execute(session=session).fetch(session=session), 6)

    def testMultiOutput(self):
        sentences = ['word1 word2', 'word2 word3', 'word3 word2 word1']

        def mapper(s):
            word_to_count = defaultdict(lambda: 0)
            for word in s.split():
                word_to_count[word] += 1

            downsides = [defaultdict(lambda: 0),
                         defaultdict(lambda: 0)]
            for word, count in word_to_count.items():
                downsides[mmh3_hash(word) % 2][word] += count

            return downsides

        def reducer(word_to_count_list):
            d = defaultdict(lambda: 0)
            for word_to_count in word_to_count_list:
                for word, count in word_to_count.items():
                    d[word] += count

            return dict(d)

        outs = [], []
        for sentence in sentences:
            out1, out2 = spawn(mapper, sentence, n_output=2)
            outs[0].append(out1)
            outs[1].append(out2)

        rs = []
        for out in outs:
            r = spawn(reducer, out)
            rs.append(r)

        result = dict()
        for wc in ExecutableTuple(rs).execute().fetch():
            result.update(wc)

        self.assertEqual(result, {'word1': 2, 'word2': 3, 'word3': 2})

    def testChainedRemote(self):
        def f(x):
            return x + 1

        def g(x):
            return x * 2

        s = spawn(g, spawn(f, 2))

        result = self.executor.execute_tileables([s])[0]
        self.assertEqual(result, 6)
