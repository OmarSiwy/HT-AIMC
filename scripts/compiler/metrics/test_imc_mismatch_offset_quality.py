"""Verify offset hook placement and restoration without a full model load."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from compiler.metrics import imc_mismatch_offset_quality as m


def main():
    original_call=m.BaseNet.__call__
    try:
        def fake_forward(self,x):
            return x if self.mvm is None else self.mvm(0,'probe',x,None,x)
        m.BaseNet.__call__=fake_forward
        model=object.__new__(m.CalibratedNet)
        x=m.np.array([[1.,2.],[3.,4.]],dtype=m.np.float32)
        bias=m.np.array([.25,-.5],dtype=m.np.float32)
        m.CURRENT.update(kind='common',A=10,format='balanced9',pooled=False)
        m.BIAS[m.key(0,'probe','balanced9','common_A10_separate')]=bias
        callback=lambda *args:2*args[2]+bias
        model.mvm=callback
        assert m.np.array_equal(model(x),2*x)
        assert model.mvm is callback
        model.mvm=None
        assert m.np.array_equal(model(x),x)
        def broken(*args):raise RuntimeError('deliberate failure')
        model.mvm=broken
        try:model(x)
        except RuntimeError:pass
        else:raise AssertionError('Exception swallowed')
        assert model.mvm is broken
    finally:
        m.BaseNet.__call__=original_call
        m.BIAS.clear();m.CURRENT.clear()
    print('PASS offset before downstream use, clean-reference identity, and hook restoration including exceptions')


if __name__=='__main__':main()
