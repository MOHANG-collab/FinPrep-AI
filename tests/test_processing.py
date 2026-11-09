import pandas as pd
from backend.main import clean_df,profile

def test_profile_and_clean():
 df=pd.DataFrame({'amount':[1,1,None],'category':['A','A','B']})
 assert profile(df)['missing']==1
 assert profile(df)['duplicates']==1
 out,operations=clean_df(df,{'drop_duplicates':True,'missing':{'amount':'median'}})
 assert len(out)==2
 assert out['amount'].isna().sum()==0
